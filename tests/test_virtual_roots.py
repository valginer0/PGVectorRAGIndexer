"""
Tests for Virtual Roots / Path Mapping (#9).

Tests cover:
- Migration 007 file structure
- _row_to_dict conversion
- DB-resilient CRUD functions
- Path resolution logic
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
# Test: Migration 007
# ===========================================================================


class TestMigration007:
    @pytest.fixture(autouse=True)
    def _load_migration(self):
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "007_virtual_roots.py"
        spec = importlib.util.spec_from_file_location("migration_007", migration_path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_migration_file_exists(self):
        path = Path(__file__).parent.parent / "alembic" / "versions" / "007_virtual_roots.py"
        assert path.exists()

    def test_migration_has_correct_revision(self):
        assert self.mod.revision == "007"
        assert self.mod.down_revision == "006"

    def test_migration_has_upgrade_and_downgrade(self):
        assert callable(getattr(self.mod, "upgrade", None))
        assert callable(getattr(self.mod, "downgrade", None))


# ===========================================================================
# Test: _row_to_dict
# ===========================================================================


class TestRowToDict:
    def test_basic_conversion(self):
        from virtual_roots import _row_to_dict
        uid = uuid.uuid4()
        now = datetime(2026, 2, 10, 14, 0, 0, tzinfo=timezone.utc)
        row = (uid, "FinanceDocs", "client-1", "/mnt/finance", now, now)
        d = _row_to_dict(row)
        assert d["id"] == str(uid)
        assert d["name"] == "FinanceDocs"
        assert d["client_id"] == "client-1"
        assert d["local_path"] == "/mnt/finance"
        assert "2026-02-10" in d["created_at"]
        assert "2026-02-10" in d["updated_at"]

    def test_none_timestamps(self):
        from virtual_roots import _row_to_dict
        uid = uuid.uuid4()
        row = (uid, "Docs", "c1", "/data", None, None)
        d = _row_to_dict(row)
        assert d["created_at"] is None
        assert d["updated_at"] is None


# ===========================================================================
# Test: DB-resilient CRUD
# ===========================================================================


class TestAddRoot:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from virtual_roots import add_root
        assert add_root("name", "client", "/path") is None


class TestRemoveRoot:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from virtual_roots import remove_root
        assert remove_root("some-id") is False


class TestRemoveRootByName:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from virtual_roots import remove_root_by_name
        assert remove_root_by_name("name", "client") is False


class TestGetRoot:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from virtual_roots import get_root
        assert get_root("some-id") is None


class TestListRoots:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from virtual_roots import list_roots
        assert list_roots() == []


class TestListRootNames:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from virtual_roots import list_root_names
        assert list_root_names() == []


class TestGetMappingsForRoot:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from virtual_roots import get_mappings_for_root
        assert get_mappings_for_root("name") == []


# ===========================================================================
# Test: Path resolution
# ===========================================================================


class TestResolvePath:
    @patch("virtual_roots._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from virtual_roots import resolve_path
        assert resolve_path("Root/file.txt", "client") is None

    @patch("virtual_roots._get_db_connection")
    def test_resolves_simple_path(self, mock_conn):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("/mnt/finance",)
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from virtual_roots import resolve_path
        result = resolve_path("FinanceDocs/reports/q1.pdf", "client-1")
        assert result is not None
        assert result.endswith(os.path.join("reports", "q1.pdf"))
        assert result.startswith("/mnt/finance")

    @patch("virtual_roots._get_db_connection")
    def test_resolves_root_only(self, mock_conn):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("/mnt/finance",)
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from virtual_roots import resolve_path
        result = resolve_path("FinanceDocs", "client-1")
        assert result == "/mnt/finance"

    @patch("virtual_roots._get_db_connection")
    def test_returns_none_for_unmapped_root(self, mock_conn):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cur

        from virtual_roots import resolve_path
        assert resolve_path("Unknown/file.txt", "client-1") is None


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestVirtualRootEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_list_endpoint(self):
        assert "/virtual-roots" in self.routes

    def test_names_endpoint(self):
        assert "/virtual-roots/names" in self.routes

    def test_mappings_endpoint(self):
        assert "/virtual-roots/{name}/mappings" in self.routes

    def test_add_endpoint(self):
        assert "/virtual-roots" in self.routes

    def test_delete_endpoint(self):
        assert "/virtual-roots/{root_id}" in self.routes

    def test_resolve_endpoint(self):
        assert "/virtual-roots/resolve" in self.routes
