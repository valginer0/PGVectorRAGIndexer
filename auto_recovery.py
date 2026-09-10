"""
Automatic database recovery for PGVectorRAGIndexer.

Detects data loss (empty database with existing backups) on startup
and restores from the most recent pg_dump backup.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from auto_backup import find_latest_backup, DEFAULT_BACKUP_DIR

logger = logging.getLogger(__name__)

RESTORE_TIMEOUT = 600  # 10 minutes for large restores

# How much of a dump to read when deciding whether it holds any rows. pg_dump
# writes the schema first, so the COPY blocks are near the end of the file for a
# small database and far into it for a large one — but we only need to find the
# FIRST row of any table, and an empty dump has none anywhere. Reading is
# streamed line by line, so this is a guard against a pathological file, not a
# size limit on real backups.
_SCAN_LINE_LIMIT = 5_000_000


def backup_contains_rows(backup_path: Path) -> bool:
    r"""Return True if *backup_path* holds at least one row of data.

    A plain-format pg_dump of an empty database still contains a complete
    schema and a ``COPY ... FROM stdin;`` header for every table, immediately
    followed by the ``\.`` terminator. Nothing distinguishes it from a real
    backup by name, timestamp or existence — only by whether any row is
    actually in it.

    This matters because restoring drops the database first. A dump with no
    rows cannot return data to anyone; restoring one can only ever destroy what
    is already there. See ``restore_from_pg_dump``.
    """
    try:
        in_copy = False
        with open(backup_path, "r", errors="replace") as f:
            for i, line in enumerate(f):
                if i > _SCAN_LINE_LIMIT:
                    logger.warning(
                        "[recovery] %s is too large to scan; assuming it holds data",
                        backup_path.name,
                    )
                    return True
                if in_copy:
                    if line.startswith("\\."):
                        in_copy = False
                    elif line.strip():
                        return True
                    continue
                stripped = line.lstrip()
                if stripped.startswith("COPY ") and "FROM stdin" in stripped:
                    in_copy = True
                elif stripped.upper().startswith("INSERT INTO "):
                    return True
    except OSError as e:
        # Unreadable is not the same as empty. Say so rather than guessing, and
        # let the caller refuse to act on a backup it cannot inspect.
        logger.warning("[recovery] Could not read %s: %s", backup_path.name, e)
        return False
    return False


def detect_data_loss(db_url: str, backup_dir: Optional[Path] = None) -> bool:
    """Check if data loss is suspected.

    Returns True when ALL of these hold:
      1. At least one .sql backup exists in backup_dir
      2. That backup actually contains rows
      3. The document_chunks table has 0 rows

    Condition 2 is what makes conditions 1 and 3 mean anything.

    The original version had only 1 and 3, with the reasoning that a fresh
    install has no backups and so cannot produce a false positive. That is true
    of a user's backups and false of ours: ``migrate.py`` writes a
    ``pre_migrate_<ts>.sql`` before running migrations, and on a brand-new
    database that dump is a few hundred bytes of empty schema. Startup then
    went: take an empty backup, create the tables, observe "a backup exists and
    document_chunks is empty", and restore the empty backup over the schema it
    had just built — leaving a database with no tables at all, on the one path
    where there was nothing to protect in the first place.

    So the question "has this system ever had data?" is asked of the backup's
    contents, which is the only place the answer actually lives. Existence,
    name and timestamp are all satisfied by a dump we wrote ourselves moments
    earlier.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    # Condition 1: backups exist
    latest = find_latest_backup(backup_dir)
    if latest is None:
        logger.debug("No backups found in %s — not a data-loss scenario", backup_dir)
        return False

    # Condition 2: the backup holds something worth restoring. Checked BEFORE
    # touching the database, because the restore path drops it.
    if not backup_contains_rows(latest):
        logger.info(
            "[recovery] Newest backup %s contains no rows — treating this as a "
            "fresh or intentionally empty database, not data loss.",
            latest.name,
        )
        return False

    # Condition 2: database is empty
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        try:
            with engine.connect() as conn:
                # Check if document_chunks table exists
                result = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_name = 'document_chunks'"
                    ")"
                ))
                table_exists = result.scalar()
                if not table_exists:
                    logger.debug("document_chunks table does not exist — likely fresh install")
                    return False

                result = conn.execute(text("SELECT COUNT(*) FROM document_chunks"))
                count = result.scalar()
                if count > 0:
                    logger.debug("Database has %d chunks — no data loss", count)
                    return False
        finally:
            engine.dispose()
    except Exception as e:
        logger.warning("Could not check database state: %s", e)
        return False

    logger.warning(
        "DATA LOSS DETECTED: document_chunks is empty but backup exists at %s",
        latest,
    )
    return True


def restore_from_pg_dump(db_url: str, backup_path: Path) -> bool:
    """Restore database from a pg_dump .sql file.

    Mirrors the logic of restore_database.sh:
      1. Connect to the 'postgres' maintenance database
      2. Terminate connections to the target database
      3. DROP and CREATE the target database
      4. Enable pgvector extension
      5. Pipe backup via psql

    Returns True on success.
    """
    parsed = urlparse(db_url)
    host = parsed.hostname or "db"
    port = str(parsed.port or 5432)
    user = parsed.username or "rag_user"
    dbname = parsed.path.lstrip("/") or "rag_vector_db"

    # Refuse before the destructive step, not after it. Everything below drops
    # the target database; a dump with no rows cannot put anything back, so
    # proceeding could only ever lose data. detect_data_loss already checks
    # this — the check is repeated here because this function is also reachable
    # directly, and the cost of being wrong is the whole database.
    if not backup_contains_rows(backup_path):
        logger.error(
            "[recovery] Refusing to restore %s: it contains no rows, and "
            "restoring drops the database first. Nothing was changed.",
            backup_path.name,
        )
        return False

    env = os.environ.copy()
    env["PGPASSWORD"] = parsed.password or ""

    def _psql(database: str, sql: str) -> bool:
        result = subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", database, "-c", sql],
            env=env, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("psql command failed: %s", result.stderr.strip())
            return False
        return True

    try:
        logger.info("[recovery] Terminating existing connections to %s...", dbname)
        _psql("postgres", (
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid();"
        ))

        logger.info("[recovery] Dropping database %s...", dbname)
        if not _psql("postgres", f"DROP DATABASE IF EXISTS {dbname};"):
            return False

        logger.info("[recovery] Creating database %s...", dbname)
        if not _psql("postgres", f"CREATE DATABASE {dbname};"):
            return False

        logger.info("[recovery] Enabling pgvector extension...")
        if not _psql(dbname, "CREATE EXTENSION IF NOT EXISTS vector;"):
            return False

        logger.info("[recovery] Restoring from %s...", backup_path.name)
        with open(backup_path, "r") as f:
            result = subprocess.run(
                ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname],
                stdin=f,
                env=env,
                capture_output=True,
                text=True,
                timeout=RESTORE_TIMEOUT,
            )

        if result.returncode != 0:
            # psql may return non-zero for non-fatal warnings; check stderr
            if "ERROR" in (result.stderr or ""):
                logger.warning("[recovery] psql restore had errors: %s", result.stderr[:500])
            else:
                logger.info("[recovery] psql restore completed with warnings")

        # Verify restoration
        verify_result = subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname,
             "-t", "-c", "SELECT COUNT(*) FROM document_chunks;"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        count = int(verify_result.stdout.strip()) if verify_result.returncode == 0 else 0

        if count > 0:
            logger.info("[recovery] Restore verified: %d chunks recovered", count)
            return True
        else:
            logger.error("[recovery] Restore verification failed: 0 chunks after restore")
            return False

    except subprocess.TimeoutExpired:
        logger.error("[recovery] Restore timed out after %d seconds", RESTORE_TIMEOUT)
        return False
    except Exception as e:
        logger.error("[recovery] Restore failed: %s", e, exc_info=True)
        return False


def auto_recover_if_needed(
    db_url: str,
    backup_dir: Optional[Path] = None,
) -> Optional[str]:
    """Main entry point: detect data loss and auto-recover.

    Called from api.py startup, after migrations but before service init.

    Returns:
        A human-readable status message if recovery was attempted, or None.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    if not detect_data_loss(db_url, backup_dir):
        return None

    backup = find_latest_backup(backup_dir)
    if backup is None:
        msg = "Data loss detected but no backup files found for recovery."
        logger.warning("[recovery] %s", msg)
        return msg

    size_mb = backup.stat().st_size / (1024 * 1024)
    logger.info(
        "[recovery] Attempting auto-recovery from %s (%.1f MB)...",
        backup.name, size_mb,
    )

    if restore_from_pg_dump(db_url, backup):
        # Re-run migrations to ensure schema is up to date
        # (backup may be from an older schema version)
        try:
            from migrate import run_migrations
            run_migrations()
        except Exception as e:
            logger.warning("[recovery] Post-restore migration failed: %s", e)

        msg = (
            f"Database automatically restored from backup '{backup.name}' "
            f"({size_mb:.1f} MB). Please verify your data."
        )
        logger.info("[recovery] %s", msg)
        return msg
    else:
        msg = (
            f"Data loss detected. Auto-recovery from '{backup.name}' failed. "
            f"Manual restore may be needed — see restore_database.sh."
        )
        logger.error("[recovery] %s", msg)
        return msg
