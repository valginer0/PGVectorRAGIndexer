"""
Integration tests for Alembic migrations using testcontainers.

These tests spin up a real pgvector/pgvector:pg16 Docker container
and validate migrations against it. Requires Docker to be running.

Run with:
    pytest tests/test_migrations_integration.py -v

Skip if Docker is not available:
    pytest tests/test_migrations_integration.py -v -k "not integration"
"""

import os
import sys
import logging
from pathlib import Path

import pytest
import psycopg2

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try to import testcontainers — skip all tests if not installed or Docker unavailable
try:
    from testcontainers.postgres import PostgresContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TESTCONTAINERS_AVAILABLE,
        reason="testcontainers not installed (pip install testcontainers[postgres])"
    ),
]


@pytest.fixture(scope="module")
def pg_container():
    """Spin up a pgvector PostgreSQL container for the test module.

    Uses pgvector/pgvector:pg16 — the same image used in production.
    Container is created once per module and torn down after all tests complete.
    """
    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="test_user",
        password="test_password",
        dbname="test_rag_db",
    ) as pg:
        yield pg


@pytest.fixture
def db_url(pg_container):
    """Get the database URL for the test container."""
    return pg_container.get_connection_url()


@pytest.fixture
def pg_connection(pg_container):
    """Get a raw psycopg2 connection to the test container."""
    conn = psycopg2.connect(
        host=pg_container.get_container_host_ip(),
        port=pg_container.get_exposed_port(5432),
        user="test_user",
        password="test_password",
        dbname="test_rag_db",
    )
    conn.autocommit = True
    yield conn
    conn.close()


def _run_alembic_upgrade(db_url: str, revision: str = "head"):
    """Run Alembic upgrade against the given database URL."""
    from alembic.config import Config
    from alembic import command

    project_root = Path(__file__).parent.parent.resolve()
    alembic_ini = project_root / "alembic.ini"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, revision)


def _run_alembic_downgrade(db_url: str, revision: str = "base"):
    """Run Alembic downgrade against the given database URL."""
    from alembic.config import Config
    from alembic import command

    project_root = Path(__file__).parent.parent.resolve()
    alembic_ini = project_root / "alembic.ini"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.downgrade(cfg, revision)


def _get_current_revision(db_url: str) -> str:
    """Get current Alembic revision from the database."""
    from sqlalchemy import create_engine
    from alembic.runtime.migration import MigrationContext

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            return context.get_current_revision()
    finally:
        engine.dispose()


class TestBaselineMigration:
    """Test baseline migration (001) on a fresh database."""

    def test_baseline_creates_table(self, db_url, pg_connection):
        """Test that baseline migration creates document_chunks table."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'document_chunks'
        """)
        tables = [row[0] for row in cursor.fetchall()]
        assert "document_chunks" in tables

    def test_baseline_creates_all_columns(self, db_url, pg_connection):
        """Test that all expected columns exist after baseline migration."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'document_chunks'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cursor.fetchall()]

        expected = [
            "chunk_id", "document_id", "chunk_index", "text_content",
            "source_uri", "embedding", "metadata", "indexed_at", "updated_at"
        ]
        for col in expected:
            assert col in columns, f"Missing column: {col}"

    def test_baseline_creates_indexes(self, db_url, pg_connection):
        """Test that all expected indexes are created."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'document_chunks'
        """)
        indexes = [row[0] for row in cursor.fetchall()]

        expected_indexes = [
            "idx_chunks_embedding_hnsw",
            "idx_chunks_document_id",
            "idx_chunks_source_uri",
            "idx_chunks_indexed_at",
            "idx_chunks_text_search",
            "idx_chunks_metadata",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"

    def test_baseline_creates_trigger(self, db_url, pg_connection):
        """Test that updated_at trigger is created."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT trigger_name FROM information_schema.triggers
            WHERE event_object_table = 'document_chunks'
        """)
        triggers = [row[0] for row in cursor.fetchall()]
        assert "update_document_chunks_updated_at" in triggers

    def test_baseline_creates_view(self, db_url, pg_connection):
        """Test that document_stats view is created."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_schema = 'public' AND table_name = 'document_stats'
        """)
        views = [row[0] for row in cursor.fetchall()]
        assert "document_stats" in views

    def test_baseline_creates_extensions(self, db_url, pg_connection):
        """Test that pgvector and pg_trgm extensions are enabled."""
        _run_alembic_upgrade(db_url, "001")

        cursor = pg_connection.cursor()
        cursor.execute("SELECT extname FROM pg_extension")
        extensions = [row[0] for row in cursor.fetchall()]
        assert "vector" in extensions
        assert "pg_trgm" in extensions

    def test_baseline_stamps_version(self, db_url):
        """Test that Alembic version table is stamped after migration."""
        _run_alembic_upgrade(db_url, "001")

        rev = _get_current_revision(db_url)
        assert rev == "001"


class TestMigrationIdempotency:
    """Test that migrations are idempotent (safe to run multiple times)."""

    def test_upgrade_twice_no_error(self, db_url):
        """Test that running upgrade twice causes no error."""
        _run_alembic_upgrade(db_url, "head")
        # Second run should be a no-op
        _run_alembic_upgrade(db_url, "head")

        rev = _get_current_revision(db_url)
        assert rev == "012"

    def test_upgrade_after_manual_schema(self, db_url, pg_connection):
        """Simulate a v2.4 database that already has init-db.sql applied.

        This is the critical upgrade path: existing users who have the
        schema but no alembic_version table.
        """
        # First, apply schema manually (simulating init-db.sql)
        cursor = pg_connection.cursor()

        # Enable extensions
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # Create table (same as init-db.sql)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id BIGSERIAL PRIMARY KEY,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text_content TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                embedding VECTOR(384),
                metadata JSONB DEFAULT '{}',
                indexed_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(document_id, chunk_index)
            )
        """)

        # Now run Alembic — should succeed without errors
        _run_alembic_upgrade(db_url, "head")

        rev = _get_current_revision(db_url)
        assert rev == "012"


class TestDataPreservation:
    """Test that migrations preserve existing data."""

    def test_data_survives_migration(self, db_url, pg_connection):
        """Test that existing data is preserved after migration."""
        # Apply migration first
        _run_alembic_upgrade(db_url, "head")

        cursor = pg_connection.cursor()

        # Insert test data
        cursor.execute("""
            INSERT INTO document_chunks
                (document_id, chunk_index, text_content, source_uri, metadata)
            VALUES
                ('doc_001', 0, 'Hello world', '/test/hello.txt', '{"file_type": "txt"}'),
                ('doc_001', 1, 'Second chunk', '/test/hello.txt', '{"file_type": "txt"}'),
                ('doc_002', 0, 'Another doc', '/test/other.pdf', '{"file_type": "pdf"}')
        """)

        # Verify data exists
        cursor.execute("SELECT COUNT(*) FROM document_chunks")
        count = cursor.fetchone()[0]
        assert count == 3

        # Run migration again (should be no-op)
        _run_alembic_upgrade(db_url, "head")

        # Verify data still exists
        cursor.execute("SELECT COUNT(*) FROM document_chunks")
        count = cursor.fetchone()[0]
        assert count == 3

        # Verify specific data
        cursor.execute(
            "SELECT text_content FROM document_chunks WHERE document_id = 'doc_001' ORDER BY chunk_index"
        )
        chunks = [row[0] for row in cursor.fetchall()]
        assert chunks == ["Hello world", "Second chunk"]

    def test_document_stats_view_works(self, db_url, pg_connection):
        """Test that document_stats view returns correct aggregated data."""
        _run_alembic_upgrade(db_url, "head")

        cursor = pg_connection.cursor()

        # Insert test data
        cursor.execute("""
            INSERT INTO document_chunks
                (document_id, chunk_index, text_content, source_uri, metadata)
            VALUES
                ('stats_doc', 0, 'Chunk 1', '/test/stats.txt', '{"file_type": "txt"}'),
                ('stats_doc', 1, 'Chunk 2', '/test/stats.txt', '{"file_type": "txt"}')
        """)

        # Query the view
        cursor.execute(
            "SELECT document_id, chunk_count FROM document_stats WHERE document_id = 'stats_doc'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "stats_doc"
        assert row[1] == 2

    def test_updated_at_trigger_works(self, db_url, pg_connection):
        """Test that the updated_at trigger fires on UPDATE."""
        _run_alembic_upgrade(db_url, "head")

        cursor = pg_connection.cursor()

        # Insert a row
        cursor.execute("""
            INSERT INTO document_chunks
                (document_id, chunk_index, text_content, source_uri)
            VALUES ('trigger_test', 0, 'Original', '/test/trigger.txt')
            RETURNING updated_at
        """)
        original_ts = cursor.fetchone()[0]

        # Small delay to ensure timestamp changes
        import time
        time.sleep(0.1)

        # Update the row
        cursor.execute("""
            UPDATE document_chunks
            SET text_content = 'Modified'
            WHERE document_id = 'trigger_test'
            RETURNING updated_at
        """)
        updated_ts = cursor.fetchone()[0]

        assert updated_ts > original_ts


class TestDowngrade:
    """Test migration downgrade (development only)."""

    def test_downgrade_removes_schema(self, db_url, pg_connection):
        """Test that downgrading to base removes all schema objects."""
        # First upgrade
        _run_alembic_upgrade(db_url, "head")

        # Then downgrade
        _run_alembic_downgrade(db_url, "base")

        # Table should be gone
        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'document_chunks'
        """)
        assert cursor.fetchone() is None

        # View should be gone
        cursor.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_schema = 'public' AND table_name = 'document_stats'
        """)
        assert cursor.fetchone() is None

    def test_upgrade_after_downgrade(self, db_url):
        """Test full cycle: upgrade → downgrade → upgrade."""
        _run_alembic_upgrade(db_url, "head")
        _run_alembic_downgrade(db_url, "base")
        _run_alembic_upgrade(db_url, "head")

        rev = _get_current_revision(db_url)
        assert rev == "012"


class TestRunMigrationsIntegration:
    """Test the run_migrations() function against a real database."""

    def test_run_migrations_with_real_db(self, db_url, pg_connection):
        """Test run_migrations() works end-to-end with real PostgreSQL."""
        from unittest.mock import patch
        from migrate import run_migrations

        # Patch _get_database_url to return our test container URL
        with patch('migrate._get_database_url', return_value=db_url):
            result = run_migrations(auto_backup=False)

        assert result is True

        # Verify schema was applied
        cursor = pg_connection.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'document_chunks'
        """)
        assert cursor.fetchone() is not None

    def test_run_migrations_twice_with_real_db(self, db_url):
        """Test run_migrations() is safe to call twice."""
        from unittest.mock import patch
        from migrate import run_migrations

        with patch('migrate._get_database_url', return_value=db_url):
            result1 = run_migrations(auto_backup=False)
            result2 = run_migrations(auto_backup=False)

        assert result1 is True
        assert result2 is True
