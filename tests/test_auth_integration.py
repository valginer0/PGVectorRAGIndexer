"""
Integration tests for API key authentication with real PostgreSQL.

Uses testcontainers to spin up a real pgvector/pgvector:pg16 container
and verify the full auth lifecycle: migration, key CRUD, and auth flow.

Run with:
    pytest tests/test_auth_integration.py -v

Requires Docker to be running.
"""

import logging
import os
import sys
from pathlib import Path

import pytest
import psycopg2

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from testcontainers.postgres import PostgresContainer

logger = logging.getLogger(__name__)

POSTGRES_IMAGE = "pgvector/pgvector:pg16"


@pytest.fixture(scope="module")
def pg_container():
    """Start a PostgreSQL container for the test module."""
    with PostgresContainer(POSTGRES_IMAGE) as pg:
        yield pg


@pytest.fixture(scope="module")
def db_url(pg_container):
    """Get database URL from container."""
    return pg_container.get_connection_url().replace("+psycopg2", "")


@pytest.fixture
def pg_connection(pg_container):
    """Get a psycopg2 connection to the container."""
    url = pg_container.get_connection_url().replace("+psycopg2", "")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    yield conn
    conn.close()


def _run_alembic_upgrade(db_url: str, revision: str = "head"):
    """Run alembic upgrade to specified revision."""
    from alembic.config import Config
    from alembic import command

    project_root = Path(__file__).parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

    command.upgrade(alembic_cfg, revision)


def _get_current_revision(db_url: str) -> str:
    """Get current alembic revision."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestApiKeysMigration:
    """Tests for the 003_api_keys migration."""

    def test_api_keys_table_exists(self, db_url, pg_connection):
        """Migration 003 creates the api_keys table."""
        _run_alembic_upgrade(db_url, "head")

        cur = pg_connection.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'api_keys'
            )
        """)
        assert cur.fetchone()[0] is True

    def test_api_keys_columns(self, db_url, pg_connection):
        """api_keys table has all expected columns."""
        _run_alembic_upgrade(db_url, "head")

        cur = pg_connection.cursor()
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'api_keys'
            ORDER BY ordinal_position
        """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

        assert "id" in columns
        assert "name" in columns
        assert "key_hash" in columns
        assert "key_prefix" in columns
        assert "created_at" in columns
        assert "last_used_at" in columns
        assert "revoked_at" in columns
        assert "expires_at" in columns

    def test_key_hash_unique(self, db_url, pg_connection):
        """key_hash column has a unique constraint."""
        _run_alembic_upgrade(db_url, "head")

        cur = pg_connection.cursor()
        # Insert a key
        cur.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix) VALUES (%s, %s, %s)",
            ("test", "hash_abc123", "pgv_sk_abc1"),
        )

        # Duplicate hash should fail
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO api_keys (name, key_hash, key_prefix) VALUES (%s, %s, %s)",
                ("test2", "hash_abc123", "pgv_sk_def2"),
            )

    def test_revision_is_005(self, db_url, pg_connection):
        """After full migration, head revision is 005."""
        _run_alembic_upgrade(db_url, "head")
        rev = _get_current_revision(db_url)
        assert rev == "012"


# ---------------------------------------------------------------------------
# Key lifecycle tests (database round-trip)
# ---------------------------------------------------------------------------


class TestKeyLifecycle:
    """Test key CRUD operations against a real database."""

    def test_create_and_lookup(self, db_url, pg_connection):
        """Create a key, then look it up by hash."""
        _run_alembic_upgrade(db_url, "head")

        from auth import generate_api_key, hash_api_key

        full_key, key_hash = generate_api_key()
        prefix = full_key[:12]

        # Insert directly
        cur = pg_connection.cursor()
        cur.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix) VALUES (%s, %s, %s) RETURNING id",
            ("test-key", key_hash, prefix),
        )
        key_id = cur.fetchone()[0]

        # Look up by hash
        cur.execute(
            "SELECT name, key_prefix FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (key_hash,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "test-key"
        assert row[1] == prefix

    def test_revoke_key(self, db_url, pg_connection):
        """Revoked keys are not returned in active lookups."""
        _run_alembic_upgrade(db_url, "head")

        from auth import generate_api_key

        full_key, key_hash = generate_api_key()

        cur = pg_connection.cursor()
        cur.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix) VALUES (%s, %s, %s) RETURNING id",
            ("revoke-test", key_hash, full_key[:12]),
        )
        key_id = cur.fetchone()[0]

        # Revoke
        cur.execute("UPDATE api_keys SET revoked_at = NOW() WHERE id = %s", (key_id,))

        # Active lookup should not find it (without grace period query)
        cur.execute(
            "SELECT id FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (key_hash,),
        )
        assert cur.fetchone() is None

    def test_expired_key(self, db_url, pg_connection):
        """Expired keys are not returned in active lookups."""
        _run_alembic_upgrade(db_url, "head")

        from auth import generate_api_key

        full_key, key_hash = generate_api_key()

        cur = pg_connection.cursor()
        cur.execute(
            "INSERT INTO api_keys (name, key_hash, key_prefix, expires_at) "
            "VALUES (%s, %s, %s, NOW() - INTERVAL '1 hour') RETURNING id",
            ("expired-test", key_hash, full_key[:12]),
        )

        # Lookup should not find expired key
        cur.execute(
            "SELECT id FROM api_keys WHERE key_hash = %s AND (expires_at IS NULL OR expires_at > NOW())",
            (key_hash,),
        )
        assert cur.fetchone() is None
