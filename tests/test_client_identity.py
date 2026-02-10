"""
Tests for Client Identity (#8).

Tests cover:
- Migration 005 file structure
- client_identity module helpers (generate_client_id, get_os_type, get_default_display_name)
- _row_to_dict conversion
- DB-resilient functions (register, heartbeat, get, list)
- API endpoint registration
"""

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Migration 005
# ===========================================================================


class TestMigration005:
    @pytest.fixture(autouse=True)
    def _load_migration(self):
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "005_clients.py"
        spec = importlib.util.spec_from_file_location("migration_005", migration_path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_migration_file_exists(self):
        path = Path(__file__).parent.parent / "alembic" / "versions" / "005_clients.py"
        assert path.exists()

    def test_migration_has_correct_revision(self):
        assert self.mod.revision == "005"
        assert self.mod.down_revision == "004"

    def test_migration_has_upgrade_and_downgrade(self):
        assert callable(getattr(self.mod, "upgrade", None))
        assert callable(getattr(self.mod, "downgrade", None))


# ===========================================================================
# Test: Desktop-side helpers
# ===========================================================================


class TestGenerateClientId:
    def test_returns_uuid_string(self):
        from client_identity import generate_client_id
        cid = generate_client_id()
        assert isinstance(cid, str)
        assert len(cid) == 36  # UUID format
        assert cid.count("-") == 4

    def test_unique_each_call(self):
        from client_identity import generate_client_id
        ids = {generate_client_id() for _ in range(10)}
        assert len(ids) == 10


class TestGetOsType:
    def test_returns_string(self):
        from client_identity import get_os_type
        result = get_os_type()
        assert isinstance(result, str)
        assert result in ("linux", "macos", "windows", "unknown") or len(result) > 0

    @patch("client_identity.platform.system", return_value="Darwin")
    def test_darwin_maps_to_macos(self, _):
        from client_identity import get_os_type
        assert get_os_type() == "macos"

    @patch("client_identity.platform.system", return_value="Linux")
    def test_linux(self, _):
        from client_identity import get_os_type
        assert get_os_type() == "linux"

    @patch("client_identity.platform.system", return_value="Windows")
    def test_windows(self, _):
        from client_identity import get_os_type
        assert get_os_type() == "windows"


class TestGetDefaultDisplayName:
    def test_returns_string(self):
        from client_identity import get_default_display_name
        name = get_default_display_name()
        assert isinstance(name, str)
        assert len(name) > 0

    @patch("client_identity.platform.node", return_value="my-laptop")
    @patch("client_identity.platform.system", return_value="Linux")
    def test_format(self, _sys, _node):
        from client_identity import get_default_display_name
        assert get_default_display_name() == "my-laptop (linux)"


# ===========================================================================
# Test: _row_to_dict
# ===========================================================================


class TestRowToDict:
    def test_basic_conversion(self):
        from client_identity import _row_to_dict
        now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        row = ("id-1", "My PC", "linux", "2.5.0", now, now)
        d = _row_to_dict(row)
        assert d["id"] == "id-1"
        assert d["display_name"] == "My PC"
        assert d["os_type"] == "linux"
        assert d["app_version"] == "2.5.0"
        assert "2026-01-15" in d["last_seen_at"]
        assert "2026-01-15" in d["created_at"]

    def test_none_timestamps(self):
        from client_identity import _row_to_dict
        row = ("id-2", "PC", "windows", None, None, None)
        d = _row_to_dict(row)
        assert d["last_seen_at"] is None
        assert d["created_at"] is None


# ===========================================================================
# Test: DB-resilient functions
# ===========================================================================


class TestRegisterClient:
    @patch("client_identity._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from client_identity import register_client
        result = register_client("id", "name", "linux")
        assert result is None


class TestHeartbeat:
    @patch("client_identity._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_false_on_db_failure(self, _mock):
        from client_identity import heartbeat
        assert heartbeat("id") is False


class TestGetClient:
    @patch("client_identity._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_none_on_db_failure(self, _mock):
        from client_identity import get_client
        assert get_client("id") is None


class TestListClients:
    @patch("client_identity._get_db_connection", side_effect=Exception("DB down"))
    def test_returns_empty_on_db_failure(self, _mock):
        from client_identity import list_clients
        assert list_clients() == []


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestClientEndpoints:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import v1_router
        self.routes = {r.path for r in v1_router.routes}

    def test_register_endpoint(self):
        assert "/clients/register" in self.routes

    def test_heartbeat_endpoint(self):
        assert "/clients/heartbeat" in self.routes

    def test_list_endpoint(self):
        assert "/clients" in self.routes
