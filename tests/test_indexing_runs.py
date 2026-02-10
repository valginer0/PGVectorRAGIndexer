"""
Tests for the Indexing Health Dashboard (#4).

Tests cover:
- indexing_runs module: start_run, complete_run, queries
- Migration 004 structure
- API endpoint definitions
"""

import os
import sys
import json
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Migration file
# ===========================================================================


def _load_migration():
    """Load migration 004 via importlib (numeric filename)."""
    import importlib.util
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "alembic", "versions", "004_indexing_runs.py",
    )
    spec = importlib.util.spec_from_file_location("migration_004", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration004:
    def test_migration_file_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "alembic", "versions", "004_indexing_runs.py",
        )
        assert os.path.exists(path)

    def test_migration_has_correct_revision(self):
        m = _load_migration()
        assert m.revision == "004"
        assert m.down_revision == "003"

    def test_migration_has_upgrade_and_downgrade(self):
        m = _load_migration()
        assert callable(getattr(m, "upgrade", None))
        assert callable(getattr(m, "downgrade", None))


# ===========================================================================
# Test: indexing_runs module helpers
# ===========================================================================


class TestJsonDumps:
    def test_serializes_dict(self):
        from indexing_runs import _json_dumps
        result = _json_dumps({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_serializes_list(self):
        from indexing_runs import _json_dumps
        result = _json_dumps([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_handles_datetime(self):
        from indexing_runs import _json_dumps
        dt = datetime(2026, 1, 1, 12, 0, 0)
        result = _json_dumps({"ts": dt})
        parsed = json.loads(result)
        assert "2026" in parsed["ts"]


class TestRowToDict:
    def test_basic_conversion(self):
        from indexing_runs import _row_to_dict
        columns = ["id", "name", "count"]
        row = ("abc-123", "test", 42)
        result = _row_to_dict(columns, row)
        assert result == {"id": "abc-123", "name": "test", "count": 42}

    def test_datetime_serialization(self):
        from indexing_runs import _row_to_dict
        dt = datetime(2026, 2, 10, 15, 30, 0)
        columns = ["id", "started_at"]
        row = ("abc", dt)
        result = _row_to_dict(columns, row)
        assert result["started_at"] == dt.isoformat()

    def test_none_datetime_stays_none(self):
        from indexing_runs import _row_to_dict
        columns = ["id", "completed_at"]
        row = ("abc", None)
        result = _row_to_dict(columns, row)
        assert result["completed_at"] is None


# ===========================================================================
# Test: start_run / complete_run with mocked DB
# ===========================================================================


def _mock_db_success():
    """Create a mock db manager that succeeds."""
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.get_connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_db


def _mock_db_failure():
    """Create a mock db manager whose get_connection raises."""
    mock_db = MagicMock()
    mock_db.get_connection.side_effect = Exception("DB down")
    return mock_db


class TestStartRun:
    @patch("indexing_runs.get_db_manager")
    def test_returns_uuid_string(self, mock_get_db):
        """start_run should return a UUID string."""
        mock_get_db.return_value = _mock_db_success()

        from indexing_runs import start_run
        run_id = start_run(trigger="manual")
        assert isinstance(run_id, str)
        assert len(run_id) == 36  # UUID format

    @patch("indexing_runs.get_db_manager")
    def test_db_failure_still_returns_id(self, mock_get_db):
        """Even if DB fails, start_run should return an ID (graceful)."""
        mock_get_db.return_value = _mock_db_failure()

        from indexing_runs import start_run
        run_id = start_run(trigger="manual")
        assert isinstance(run_id, str)
        assert len(run_id) == 36


class TestCompleteRun:
    @patch("indexing_runs.get_db_manager")
    def test_does_not_raise_on_db_failure(self, mock_get_db):
        """complete_run should not raise even if DB fails."""
        mock_get_db.return_value = _mock_db_failure()

        from indexing_runs import complete_run
        # Should not raise
        complete_run("fake-uuid", status="success", files_scanned=1)


# ===========================================================================
# Test: Query functions with mocked DB
# ===========================================================================


class TestGetRecentRuns:
    @patch("indexing_runs.get_db_manager")
    def test_returns_empty_on_error(self, mock_get_db):
        mock_get_db.return_value = _mock_db_failure()

        from indexing_runs import get_recent_runs
        result = get_recent_runs()
        assert result == []


class TestGetRunSummary:
    @patch("indexing_runs.get_db_manager")
    def test_returns_defaults_on_error(self, mock_get_db):
        mock_get_db.return_value = _mock_db_failure()

        from indexing_runs import get_run_summary
        result = get_run_summary()
        assert result["total_runs"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0


class TestGetRunById:
    @patch("indexing_runs.get_db_manager")
    def test_returns_none_on_error(self, mock_get_db):
        mock_get_db.return_value = _mock_db_failure()

        from indexing_runs import get_run_by_id
        result = get_run_by_id("fake-uuid")
        assert result is None


# ===========================================================================
# Test: API endpoints exist
# ===========================================================================


class TestHealthDashboardEndpoints:
    def test_runs_endpoint_registered(self):
        from api import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/indexing/runs" in routes or any(
            "/indexing/runs" in str(r.path) for r in app.routes
        )

    def test_summary_endpoint_registered(self):
        from api import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/indexing/runs/summary" in routes or any(
            "/indexing/runs/summary" in str(r.path) for r in app.routes
        )

    def test_run_detail_endpoint_registered(self):
        from api import app
        routes = [r.path for r in app.routes]
        assert "/api/v1/indexing/runs/{run_id}" in routes or any(
            "/indexing/runs/{run_id}" in str(r.path) for r in app.routes
        )
