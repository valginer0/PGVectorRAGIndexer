"""
Automatic pg_dump backup and rotation for PGVectorRAGIndexer.

Provides reusable backup functions used by:
- migrate.py (pre-migration safety backup)
- api.py (startup backup)
- server_scheduler.py (periodic backup — future)
"""

import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = Path("/app/backups")
DEFAULT_KEEP = 5
TIMEOUT_SECONDS = 300  # 5 minutes


def run_pg_dump_backup(
    db_url: str,
    backup_dir: Optional[Path] = None,
    prefix: str = "auto_backup",
) -> Optional[Path]:
    """Run pg_dump and save a timestamped .sql backup.

    Args:
        db_url: PostgreSQL connection string (postgresql://user:pass@host:port/db).
        backup_dir: Directory to write backup into. Defaults to /app/backups.
        prefix: Filename prefix (e.g. "pre_migrate", "startup_backup", "auto_backup").

    Returns:
        Path to the backup file on success, None on failure.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{prefix}_{timestamp}.sql"

    try:
        parsed = urlparse(db_url)
        env = os.environ.copy()
        env["PGPASSWORD"] = parsed.password or ""

        result = subprocess.run(
            [
                "pg_dump",
                "-h", parsed.hostname or "db",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "rag_user",
                "-d", parsed.path.lstrip("/") or "rag_vector_db",
                "-f", str(backup_file),
                "--no-owner",
                "--no-privileges",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

        if result.returncode == 0:
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            logger.info("Backup saved: %s (%.1f MB)", backup_file, size_mb)
            return backup_file
        else:
            logger.warning("pg_dump failed (exit %d): %s", result.returncode, result.stderr)
            return None

    except FileNotFoundError:
        logger.warning(
            "pg_dump not found — skipping backup. "
            "Install postgresql-client for automatic backups."
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning("pg_dump timed out after %d seconds — skipping backup", TIMEOUT_SECONDS)
        return None
    except Exception as e:
        logger.warning("Backup failed: %s", e)
        return None


def rotate_backups(
    backup_dir: Optional[Path] = None,
    prefix: str = "auto_backup",
    keep: int = DEFAULT_KEEP,
) -> int:
    """Delete oldest backups beyond the retention count.

    Only deletes files matching ``{prefix}_*.sql`` in *backup_dir*.

    Returns:
        Number of files deleted.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    if not backup_dir.is_dir():
        return 0

    pattern = f"{prefix}_*.sql"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    deleted = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            logger.info("Rotated old backup: %s", old.name)
            deleted += 1
        except OSError as e:
            logger.warning("Failed to delete old backup %s: %s", old.name, e)
    return deleted


def find_latest_backup(
    backup_dir: Optional[Path] = None,
    prefixes: Tuple[str, ...] = ("auto_backup_", "startup_backup_", "pre_migrate_", "pgvector_backup_"),
) -> Optional[Path]:
    """Find the most recent .sql backup file across all prefix types.

    Returns:
        Path to the newest backup, or None if no backups exist.
    """
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    if not backup_dir.is_dir():
        return None

    candidates = []
    for f in backup_dir.iterdir():
        if not f.is_file() or not f.suffix == ".sql":
            continue
        if any(f.name.startswith(p) for p in prefixes):
            candidates.append(f)

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def has_any_backup(backup_dir: Optional[Path] = None) -> bool:
    """Check if any .sql backup exists in the backup directory."""
    return find_latest_backup(backup_dir) is not None
