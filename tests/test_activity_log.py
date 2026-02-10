"""
Tests for Activity and Audit Log (#10).

Tests cover:
- Migration 008 file structure
- _row_to_dict conversion
- DB-resilient functions (log, query, count, action types, export, retention)
- CSV export format
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
# Test: Migration 008
# ===========================================================================


class TestMigration008:
    @pytest.fixture(autouse=True)
    def _load_migration(self):
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "008_activity_log.py"
        spec = importlib.util.spec_from_file_location("migration_008", migration_path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_migration_file_exists(self):
        path = Path(__file__).parent.parent / "alembic" / "versions" / "008_activity_log.py"
        assert path.exists()

    def test_migration_has_correct_revision(self):
        assert self.mod.revision == "008"
        assert self.mod.down_revision == "007"

    def test_migration_has_upgrade_and_downgrade(self):
        assert callable(getattr(self.mod, "upgrade", None))
        assert callable(getattr(self.mod, "downgrade", None))


# ===========================================================================
# Test: _row_to_dict
# ===========================================================================


class TestRowToDict:
    def test_basic_conversion(self):
        from activity_log import _row_to_dict
        uid = uuid.uuid4()
        now = datetime(2026, 2, 10, 15, 0, 0, tzinfo=timezone.utc)
        row = (uid, now, "client-1", None, "index_start", {"file": "test.pdf"})
        d = _row_to_dict(row)
        assert d["id"] == str(uid)
        assert "2026-02-10" in d["ts"]
        assert d["client_id"] == "client-1"
        assert d["user_id"] is None
        assert d["action"] == "index_start"
        assert d["details"]["file"] == "test.pdf"

    def test_none_timestamp(self):
        from activity_log import _row_to_dict
        uid = uuid.uuid4()
        row = (uid, None, None, None, "search", {})
        d = _row_to_dict(row)
        assert d["ts"] is None


# ===========================================================================
# Test: DB-resilient functions
# ===========================================================================


class TestLogActivity:
    @patch("activity_log._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from activity_log import log_activity
        assert log_activity("test_action") is None


class TestGetRecent:
    @patch("activity_log._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from activity_log import get_recent
        assert get_recent() == []


class TestGetActivityCount:
    @patch("activity_log._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_zero_on_db_failure(self, _mock):
        from activity_log import get_activity_count
        assert get_activity_count() == 0


class TestGetActionTypes:
    @patch("activity_log._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from activity_log import get_action_types
        assert get_action_types() == []


class TestApplyRetention:
    @patch("activity_log._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_zero_on_db_failure(self, _mock):
        from activity_log import apply_retention
        assert apply_retention(90) == 0


# ===========================================================================
# Test: CSV export
# ===========================================================================


class TestExportCsv:
    @patch("activity_log.get_recent")
    def test_empty_export(self, mock_recent):
        mock_recent.return_value = []
        from activity_log import export_csv
        csv_data = export_csv()
        assert "id,ts,client_id,user_id,action,details" in csv_data

    @patch("activity_log.get_recent")
    def test_export_with_entries(self, mock_recent):
        mock_recent.return_value = [
            {
                "id": "abc-123",
                "ts": "2026-02-10T15:00:00+00:00",
                "client_id": "c1",
                "user_id": None,
                "action": "upload",
                "details": {"file": "test.pdf"},
            }
        ]
        from activity_log import export_csv
        csv_data = export_csv()
        assert "abc-123" in csv_data
        assert "upload" in csv_data
        assert "test.pdf" in csv_data


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestActivityLogEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_get_activity_endpoint(self):
        assert "/activity" in self.routes

    def test_post_activity_endpoint(self):
        assert "/activity" in self.routes

    def test_actions_endpoint(self):
        assert "/activity/actions" in self.routes

    def test_export_endpoint(self):
        assert "/activity/export" in self.routes

    def test_retention_endpoint(self):
        assert "/activity/retention" in self.routes
