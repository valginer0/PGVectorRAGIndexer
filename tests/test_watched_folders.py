"""
Tests for Watched Folders (#6).

Tests cover:
- Migration 006 file structure
- watched_folders module helpers (_row_to_dict)
- DB-resilient CRUD functions
- API endpoint registration
"""

import importlib.util
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Migration 006
# ===========================================================================


class TestMigration006:
    @pytest.fixture(autouse=True)
    def _load_migration(self):
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "006_watched_folders.py"
        spec = importlib.util.spec_from_file_location("migration_006", migration_path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_migration_file_exists(self):
        path = Path(__file__).parent.parent / "alembic" / "versions" / "006_watched_folders.py"
        assert path.exists()

    def test_migration_has_correct_revision(self):
        assert self.mod.revision == "006"
        assert self.mod.down_revision == "005"

    def test_migration_has_upgrade_and_downgrade(self):
        assert callable(getattr(self.mod, "upgrade", None))
        assert callable(getattr(self.mod, "downgrade", None))


# ===========================================================================
# Test: _row_to_dict
# ===========================================================================


class TestRowToDict:
    def test_basic_conversion(self):
        from watched_folders import _row_to_dict
        uid = uuid.uuid4()
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        row = (uid, "/data/docs", True, "0 */6 * * *", now, None, "client-1", now, now, {})
        d = _row_to_dict(row)
        assert d["id"] == str(uid)
        assert d["folder_path"] == "/data/docs"
        assert d["enabled"] is True
        assert d["schedule_cron"] == "0 */6 * * *"
        assert "2026-02-10" in d["last_scanned_at"]
        assert d["last_run_id"] is None
        assert d["client_id"] == "client-1"

    def test_uuid_last_run_id(self):
        from watched_folders import _row_to_dict
        uid = uuid.uuid4()
        run_uid = uuid.uuid4()
        now = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        row = (uid, "/data", True, "0 0 * * *", now, run_uid, None, now, now, {})
        d = _row_to_dict(row)
        assert d["last_run_id"] == str(run_uid)

    def test_none_timestamps(self):
        from watched_folders import _row_to_dict
        uid = uuid.uuid4()
        row = (uid, "/data", True, "0 0 * * *", None, None, None, None, None, {})
        d = _row_to_dict(row)
        assert d["last_scanned_at"] is None
        assert d["created_at"] is None
        assert d["updated_at"] is None


# ===========================================================================
# Test: DB-resilient CRUD
# ===========================================================================


class TestAddFolder:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from watched_folders import add_folder
        assert add_folder("/data/docs", client_id="test-client") is None


class TestRemoveFolder:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from watched_folders import remove_folder
        assert remove_folder("some-id") is False


class TestUpdateFolder:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from watched_folders import update_folder
        assert update_folder("some-id", enabled=False) is None


class TestGetFolder:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from watched_folders import get_folder
        assert get_folder("some-id") is None


class TestListFolders:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from watched_folders import list_folders
        assert list_folders() == []


class TestMarkScanned:
    @patch("watched_folders._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from watched_folders import mark_scanned
        assert mark_scanned("some-id") is False


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestWatchedFolderEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_list_endpoint(self):
        assert "/watched-folders" in self.routes

    def test_add_endpoint(self):
        assert "/watched-folders" in self.routes

    def test_update_endpoint(self):
        assert "/watched-folders/{folder_id}" in self.routes

    def test_delete_endpoint(self):
        assert "/watched-folders/{folder_id}" in self.routes

    def test_scan_endpoint(self):
        assert "/watched-folders/{folder_id}/scan" in self.routes
