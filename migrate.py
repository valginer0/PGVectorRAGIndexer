"""
Database migration runner for PGVectorRAGIndexer.

Provides a standalone migration runner with pre-migration backup safety.
Can be called from api.py startup, Docker entrypoint, or CLI.

Usage:
    # From Python (e.g., in api.py lifespan):
    from migrate import run_migrations
    run_migrations()

    # From CLI:
    python migrate.py
"""

import os
import sys
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)

# Directory where this file lives (project root)
PROJECT_ROOT = Path(__file__).parent.resolve()


def _get_alembic_config() -> Config:
    """Create Alembic config pointing to alembic.ini in project root."""
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    cfg = Config(str(alembic_ini))
    # Ensure script_location is absolute
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg


def _get_database_url() -> str:
    """Get database URL from application config."""
    from config import get_config
    return get_config().database.connection_string


def _is_docker_mode() -> bool:
    """Detect if running inside Docker.

    Checks for common Docker indicators:
    - DB_HOST=db (set in docker-compose.yml)
    - /.dockerenv file exists
    - Running as PID 1 inside container
    """
    if os.environ.get("DB_HOST") == "db":
        return True
    if Path("/.dockerenv").exists():
        return True
    return False


def _get_pending_migrations(db_url: str, alembic_cfg: Config) -> list:
    """Check for pending migrations.

    Returns list of pending revision IDs, empty if database is up to date.
    """
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        if current_rev == head_rev:
            return []

        # Collect all revisions between current and head
        pending = []
        for rev in script.walk_revisions():
            if rev.revision == current_rev:
                break
            pending.append(rev.revision)

        return pending
    finally:
        engine.dispose()


def _run_pg_dump(db_url: str) -> bool:
    """Run pg_dump backup before migration (Docker mode).

    Saves backup to /app/backups/pre_migrate_<timestamp>.sql
    Returns True if backup succeeded, False otherwise.
    """
    backup_dir = Path("/app/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"pre_migrate_{timestamp}.sql"

    try:
        # Parse connection details from URL
        # Format: postgresql://user:password@host:port/dbname
        from urllib.parse import urlparse
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
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            logger.info(
                f"Pre-migration backup saved: {backup_file} ({size_mb:.1f} MB)"
            )
            return True
        else:
            logger.warning(
                f"pg_dump failed (exit {result.returncode}): {result.stderr}"
            )
            return False

    except FileNotFoundError:
        logger.warning(
            "pg_dump not found — skipping pre-migration backup. "
            "Install postgresql-client for automatic backups."
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("pg_dump timed out after 5 minutes — skipping backup")
        return False
    except Exception as e:
        logger.warning(f"Pre-migration backup failed: {e}")
        return False


def _check_recent_backup() -> bool:
    """Check if a recent backup exists (desktop mode).

    Looks for backup files less than 24 hours old in common locations.
    Returns True if a recent backup was found.
    """
    # Check common backup locations
    backup_dirs = [
        Path.home() / ".pgvector-backups",
        Path.home() / "pgvector-backups",
        PROJECT_ROOT / "backups",
    ]

    cutoff = datetime.now(timezone.utc).timestamp() - (24 * 3600)

    for backup_dir in backup_dirs:
        if backup_dir.exists():
            for f in backup_dir.iterdir():
                if f.suffix in (".sql", ".dump", ".backup"):
                    if f.stat().st_mtime > cutoff:
                        logger.info(f"Recent backup found: {f}")
                        return True

    return False


def run_migrations(auto_backup: bool = True) -> bool:
    """Run all pending Alembic migrations with pre-migration backup safety.

    Args:
        auto_backup: If True, perform backup safety checks before migrating.
            - Docker mode: auto-run pg_dump
            - Desktop mode: warn if no recent backup found

    Returns:
        True if migrations ran successfully (or no migrations needed),
        False if migrations failed.
    """
    try:
        alembic_cfg = _get_alembic_config()
        db_url = _get_database_url()

        # Check for pending migrations
        pending = _get_pending_migrations(db_url, alembic_cfg)

        if not pending:
            logger.info("Database schema is up to date — no migrations needed")
            return True

        logger.info(
            f"Found {len(pending)} pending migration(s): {pending}"
        )

        # Pre-migration backup safety
        if auto_backup:
            if _is_docker_mode():
                logger.info("Docker mode detected — running pre-migration backup")
                backup_ok = _run_pg_dump(db_url)
                if not backup_ok:
                    logger.warning(
                        "Pre-migration backup failed, but proceeding with migration. "
                        "Consider backing up your database manually."
                    )
            else:
                if not _check_recent_backup():
                    logger.warning(
                        "⚠️  No recent database backup found (< 24h). "
                        "Consider backing up your database before upgrading. "
                        "Proceeding with migration..."
                    )

        # Run migrations
        logger.info("Applying database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
        return True

    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        logger.error(
            "The application may not work correctly until migrations are applied. "
            "Check the database connection and try again."
        )
        return False


if __name__ == "__main__":
    # CLI usage: python migrate.py
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    success = run_migrations()
    sys.exit(0 if success else 1)
