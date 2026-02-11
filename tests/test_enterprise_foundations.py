"""
Tests for #16 Enterprise Foundations (Phase 1).

Tests cover:
- Migration 010: users table structure
- users.py: _row_to_dict, role validation, DB resilience
- auth.py: require_admin dependency
- API endpoint registration
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Migration 010
# ===========================================================================


class TestMigration010:
    def test_migration_file_exists(self):
        assert (PROJECT_ROOT / "alembic" / "versions" / "010_users.py").exists()

    def test_migration_has_correct_revision(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_010",
            str(PROJECT_ROOT / "alembic" / "versions" / "010_users.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "010"
        assert mod.down_revision == "009"

    def test_migration_has_upgrade_and_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_010",
            str(PROJECT_ROOT / "alembic" / "versions" / "010_users.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


# ===========================================================================
# Test: users.py module
# ===========================================================================


class TestUsersConstants:
    def test_valid_roles(self):
        from users import VALID_ROLES, ROLE_ADMIN, ROLE_USER
        assert ROLE_ADMIN in VALID_ROLES
        assert ROLE_USER in VALID_ROLES

    def test_valid_auth_providers(self):
        from users import VALID_AUTH_PROVIDERS, AUTH_PROVIDER_API_KEY, AUTH_PROVIDER_SAML
        assert AUTH_PROVIDER_API_KEY in VALID_AUTH_PROVIDERS
        assert AUTH_PROVIDER_SAML in VALID_AUTH_PROVIDERS


class TestRowToDict:
    def test_basic_conversion(self):
        from users import _row_to_dict
        now = datetime.now(timezone.utc)
        row = ("u1", "a@b.com", "Alice", "admin", "api_key", 1, "c1", now, now, now, True)
        d = _row_to_dict(row)
        assert d["id"] == "u1"
        assert d["email"] == "a@b.com"
        assert d["role"] == "admin"
        assert d["is_active"] is True
        assert isinstance(d["created_at"], str)

    def test_none_timestamps(self):
        from users import _row_to_dict
        row = ("u2", None, None, "user", "api_key", None, None, None, None, None, True)
        d = _row_to_dict(row)
        assert d["last_login_at"] is None


class TestUsersDBResilience:
    """Test that functions return safe defaults on DB failure."""

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_create_user_returns_none(self, _mock):
        from users import create_user
        assert create_user(email="x@y.com") is None

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_get_user_returns_none(self, _mock):
        from users import get_user
        assert get_user("u1") is None

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_get_user_by_email_returns_none(self, _mock):
        from users import get_user_by_email
        assert get_user_by_email("x@y.com") is None

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_get_user_by_api_key_returns_none(self, _mock):
        from users import get_user_by_api_key
        assert get_user_by_api_key(1) is None

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_list_users_returns_empty(self, _mock):
        from users import list_users
        assert list_users() == []

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_update_user_returns_none(self, _mock):
        from users import update_user
        assert update_user("u1", email="new@x.com") is None

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_delete_user_returns_false(self, _mock):
        from users import delete_user
        assert delete_user("u1") is False

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_is_admin_returns_false(self, _mock):
        from users import is_admin
        assert is_admin("u1") is False

    @patch("users._get_db_connection", side_effect=Exception("DB down"))
    def test_count_admins_returns_zero(self, _mock):
        from users import count_admins
        assert count_admins() == 0


class TestUsersRoleValidation:
    def test_create_user_rejects_invalid_role(self):
        from users import create_user
        assert create_user(role="superadmin") is None

    def test_create_user_rejects_invalid_auth_provider(self):
        from users import create_user
        assert create_user(auth_provider="magic") is None

    def test_update_user_rejects_invalid_role(self):
        from users import update_user
        assert update_user("u1", role="superadmin") is None


# ===========================================================================
# Test: require_admin dependency
# ===========================================================================


class TestRequireAdmin:
    def test_require_admin_exists(self):
        from auth import require_admin
        assert callable(require_admin)

    def test_require_admin_is_async(self):
        import asyncio
        from auth import require_admin
        assert asyncio.iscoroutinefunction(require_admin)


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestUserEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_list_users_endpoint(self):
        assert "/api/v1/users" in self.routes

    def test_get_user_endpoint(self):
        assert "/api/v1/users/{user_id}" in self.routes

    def test_create_user_endpoint(self):
        assert "/api/v1/users" in self.routes

    def test_delete_user_endpoint(self):
        assert "/api/v1/users/{user_id}" in self.routes

    def test_change_role_endpoint(self):
        assert "/api/v1/users/{user_id}/role" in self.routes
