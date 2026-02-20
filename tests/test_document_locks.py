"""
Tests for Document Locks (#3 Multi-User, Phase 1).

Tests cover:
- Migration 009 file structure
- _row_to_dict conversion
- DB-resilient functions (acquire, release, force_release, check, list, cleanup)
- Lock conflict logic (same client extends, different client blocked)
- API endpoint registration
"""

import importlib.util
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Migration 009
# ===========================================================================


class TestMigration009:
    @pytest.fixture(autouse=True)
    def _load_migration(self):
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "009_document_locks.py"
        spec = importlib.util.spec_from_file_location("migration_009", migration_path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_migration_file_exists(self):
        path = Path(__file__).parent.parent / "alembic" / "versions" / "009_document_locks.py"
        assert path.exists()

    def test_migration_has_correct_revision(self):
        assert self.mod.revision == "009"
        assert self.mod.down_revision == "008"

    def test_migration_has_upgrade_and_downgrade(self):
        assert callable(getattr(self.mod, "upgrade", None))
        assert callable(getattr(self.mod, "downgrade", None))


# ===========================================================================
# Test: _row_to_dict
# ===========================================================================


class TestRowToDict:
    def test_basic_conversion(self):
        from document_locks import _row_to_dict
        uid = uuid.uuid4()
        now = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)
        expires = now + timedelta(minutes=10)
        row = (uid, "/docs/test.pdf", "client-1", now, expires, "indexing")
        d = _row_to_dict(row)
        assert d["id"] == str(uid)
        assert d["source_uri"] == "/docs/test.pdf"
        assert d["client_id"] == "client-1"
        assert "2026-02-10" in d["locked_at"]
        assert "2026-02-10" in d["expires_at"]
        assert d["lock_reason"] == "indexing"

    def test_none_timestamps(self):
        from document_locks import _row_to_dict
        uid = uuid.uuid4()
        row = (uid, "/test.pdf", "c1", None, None, "indexing")
        d = _row_to_dict(row)
        assert d["locked_at"] is None
        assert d["expires_at"] is None


# ===========================================================================
# Test: DB-resilient functions
# ===========================================================================


class TestAcquireLock:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_error_on_db_failure(self, _mock):
        from document_locks import acquire_lock
        result = acquire_lock("/test.pdf", "client-1")
        assert result["ok"] is False
        assert "error" in result


class TestReleaseLock:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from document_locks import release_lock
        assert release_lock("/test.pdf", "client-1") is False


class TestForceReleaseLock:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from document_locks import force_release_lock
        assert force_release_lock("/test.pdf") is False


class TestCheckLock:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from document_locks import check_lock
        assert check_lock("/test.pdf") is None


class TestListLocks:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from document_locks import list_locks
        assert list_locks() == []


class TestCleanupExpiredLocks:
    @patch("document_locks._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_zero_on_db_failure(self, _mock):
        from document_locks import cleanup_expired_locks
        assert cleanup_expired_locks() == 0


# ===========================================================================
# Test: Lock conflict logic (with mocked DB)
# ===========================================================================


class TestLockConflict:
    @patch("document_locks._get_db_connection")
    def test_acquire_new_lock(self, mock_conn):
        """Acquiring a lock on an unlocked document succeeds."""
        now = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)
        expires = now + timedelta(minutes=10)
        lock_id = uuid.uuid4()

        mock_cur = MagicMock()
        # cleanup expired: no-op
        mock_cur.execute.return_value = None
        # check existing: none
        mock_cur.fetchone.side_effect = [
            None,  # no existing lock
            (lock_id, "/test.pdf", "client-1", now, expires, "indexing"),  # INSERT RETURNING
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from document_locks import acquire_lock
        result = acquire_lock("/test.pdf", "client-1")
        assert result["ok"] is True
        assert result["extended"] is False
        assert result["lock"]["source_uri"] == "/test.pdf"

    @patch("document_locks._get_db_connection")
    def test_same_client_extends_lock(self, mock_conn):
        """Same client re-acquiring extends the lock."""
        now = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)
        expires = now + timedelta(minutes=10)
        lock_id = uuid.uuid4()

        mock_cur = MagicMock()
        # existing lock by same client
        mock_cur.fetchone.side_effect = [
            (lock_id, "/test.pdf", "client-1", now, expires, "indexing"),  # existing
            (lock_id, "/test.pdf", "client-1", now, expires, "indexing"),  # UPDATE RETURNING
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from document_locks import acquire_lock
        result = acquire_lock("/test.pdf", "client-1")
        assert result["ok"] is True
        assert result["extended"] is True

    @patch("document_locks._get_db_connection")
    def test_different_client_blocked(self, mock_conn):
        """Different client trying to lock an already-locked document is blocked."""
        now = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)
        expires = now + timedelta(minutes=10)
        lock_id = uuid.uuid4()

        mock_cur = MagicMock()
        # existing lock by different client
        mock_cur.fetchone.side_effect = [
            (lock_id, "/test.pdf", "client-A", now, expires, "indexing"),  # existing
        ]
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from document_locks import acquire_lock
        result = acquire_lock("/test.pdf", "client-B")
        assert result["ok"] is False
        assert "client-A" in result["error"]
        assert "holder" in result


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestDocumentLockEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_acquire_endpoint(self):
        assert "/documents/locks/acquire" in self.routes

    def test_release_endpoint(self):
        assert "/documents/locks/release" in self.routes

    def test_force_release_endpoint(self):
        assert "/documents/locks/force-release" in self.routes

    def test_list_endpoint(self):
        assert "/documents/locks" in self.routes

    def test_check_endpoint(self):
        assert "/documents/locks/check" in self.routes

    def test_cleanup_endpoint(self):
        assert "/documents/locks/cleanup" in self.routes
