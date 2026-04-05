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


def detect_data_loss(db_url: str, backup_dir: Optional[Path] = None) -> bool:
    """Check if data loss is suspected.

    Returns True when BOTH conditions are met:
      1. At least one .sql backup exists in backup_dir (meaning data existed before)
      2. The document_chunks table has 0 rows

    Fresh installs (no backups) return False — no false positives.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR

    # Condition 1: backups exist
    latest = find_latest_backup(backup_dir)
    if latest is None:
        logger.debug("No backups found in %s — not a data-loss scenario", backup_dir)
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
