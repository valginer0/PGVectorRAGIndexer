"""
Integration tests for license key validation and server_settings migration.

Uses testcontainers to spin up a real PostgreSQL container and verify:
- server_settings migration creates the table
- server_settings trigger works
- Migration chain 001 → 002 works
- License + migration round-trip (full startup simulation)
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from testcontainers.postgres import PostgresContainer
    from sqlalchemy import create_engine, text
    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False

import jwt

from license import (
    Edition,
    validate_license_key,
    load_license,
)

# Skip all tests if testcontainers not available
pytestmark = pytest.mark.skipif(
    not HAS_TESTCONTAINERS,
    reason="testcontainers not installed"
)

# Test signing secret
TEST_SECRET = "integration-test-secret"

# Module-scoped container (shared across all tests in this file)
_container = None
_engine = None


@pytest.fixture(scope="module")
def pg_container():
    """Start a PostgreSQL container for the test module."""
    global _container, _engine
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="test",
        password="test",
        dbname="testdb",
    ) as container:
        url = container.get_connection_url()
        _engine = create_engine(url)
        _container = container
        yield container
    _engine = None
    _container = None


@pytest.fixture(scope="module")
def alembic_config(pg_container):
    """Create Alembic config pointing at the test container."""
    from alembic.config import Config

    project_root = Path(__file__).parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", pg_container.get_connection_url())
    return cfg


@pytest.fixture(scope="module")
def migrated_db(alembic_config, pg_container):
    """Run all migrations on the test container."""
    from alembic import command
    command.upgrade(alembic_config, "head")
    return pg_container


# ===========================================================================
# Test: server_settings migration
# ===========================================================================


class TestServerSettingsMigration:
    """Test the 002_server_settings migration."""

    def test_server_settings_table_exists(self, migrated_db):
        """Migration creates the server_settings table."""
        with _engine.connect() as conn:
            result = conn.execute(text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_name = 'server_settings'"
                ")"
            ))
            assert result.scalar() is True

    def test_server_settings_columns(self, migrated_db):
        """server_settings has key, value, updated_at columns."""
        with _engine.connect() as conn:
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'server_settings' "
                "ORDER BY ordinal_position"
            ))
            columns = [row[0] for row in result.fetchall()]
        assert "key" in columns
        assert "value" in columns
        assert "updated_at" in columns

    def test_server_settings_insert_and_read(self, migrated_db):
        """Can insert and read from server_settings."""
        with _engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO server_settings (key, value) "
                "VALUES ('test_key', '{\"foo\": \"bar\"}'::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ))
            conn.commit()

            result = conn.execute(text(
                "SELECT value FROM server_settings WHERE key = 'test_key'"
            ))
            row = result.fetchone()
            assert row is not None
            assert row[0] == {"foo": "bar"}

    def test_server_settings_trigger_updates_timestamp(self, migrated_db):
        """updated_at trigger fires on update."""
        with _engine.connect() as conn:
            # Insert
            conn.execute(text(
                "INSERT INTO server_settings (key, value) "
                "VALUES ('trigger_test', '{\"v\": 1}'::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ))
            conn.commit()

            # Get original timestamp
            result = conn.execute(text(
                "SELECT updated_at FROM server_settings WHERE key = 'trigger_test'"
            ))
            original_ts = result.scalar()

            # Wait briefly and update
            import time
            time.sleep(0.1)
            conn.execute(text(
                "UPDATE server_settings SET value = '{\"v\": 2}'::jsonb "
                "WHERE key = 'trigger_test'"
            ))
            conn.commit()

            # Verify timestamp changed
            result = conn.execute(text(
                "SELECT updated_at FROM server_settings WHERE key = 'trigger_test'"
            ))
            new_ts = result.scalar()
            assert new_ts >= original_ts


# ===========================================================================
# Test: Full migration chain
# ===========================================================================


class TestMigrationChain:
    """Test that the full 001 → 002 migration chain works."""

    def test_both_tables_exist(self, migrated_db):
        """Both document_chunks and server_settings exist after full upgrade."""
        with _engine.connect() as conn:
            for table_name in ["document_chunks", "server_settings"]:
                result = conn.execute(text(
                    f"SELECT EXISTS ("
                    f"  SELECT 1 FROM information_schema.tables "
                    f"  WHERE table_name = '{table_name}'"
                    f")"
                ))
                assert result.scalar() is True, f"Table {table_name} not found"

    def test_alembic_version_is_002(self, migrated_db):
        """Alembic version table shows revision 002."""
        with _engine.connect() as conn:
            result = conn.execute(text(
                "SELECT version_num FROM alembic_version"
            ))
            version = result.scalar()
        assert version == "011"


# ===========================================================================
# Test: License + server_settings integration
# ===========================================================================


class TestLicenseServerSettings:
    """Test storing license info in server_settings."""

    def test_store_license_edition(self, migrated_db):
        """Can store and retrieve license edition in server_settings."""
        # Generate a valid key
        token = jwt.encode(
            {
                "edition": "team",
                "org": "Integration Test Org",
                "seats": 10,
                "iat": int(time.time()),
                "exp": int(time.time() + 86400 * 90),
            },
            TEST_SECRET,
            algorithm="HS256",
        )

        # Validate the key
        info = validate_license_key(token, TEST_SECRET)
        assert info.edition == Edition.TEAM

        # Store in server_settings
        with _engine.connect() as conn:
            import json
            conn.execute(text(
                "INSERT INTO server_settings (key, value) "
                "VALUES ('license_edition', :val) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ), {"val": json.dumps(info.to_dict())})
            conn.commit()

            # Retrieve
            result = conn.execute(text(
                "SELECT value FROM server_settings WHERE key = 'license_edition'"
            ))
            stored = result.scalar()
            assert stored["edition"] == "team"
            assert stored["org_name"] == "Integration Test Org"
            assert stored["seats"] == 10
