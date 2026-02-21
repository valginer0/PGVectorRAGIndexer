"""
Tests for #16 Enterprise Foundations Phase 4a — Custom Roles & Permissions.

Tests cover:
- Permission constants
- Built-in role definitions
- Config loading (defaults + JSON file)
- Role validation (dynamic, accepts custom roles)
- Permission checks (has_permission, system.admin grants all)
- Role listing and info
- Permission listing
- require_permission() factory in auth.py
- require_admin() delegation to require_permission
- API endpoint registration
- users.py dynamic role validation
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Permission constants
# ===========================================================================


class TestPermissionConstants:
    def test_all_permissions_defined(self):
        from role_permissions import ALL_PERMISSIONS
        assert len(ALL_PERMISSIONS) == 10

    def test_all_permissions_is_frozenset(self):
        from role_permissions import ALL_PERMISSIONS
        assert isinstance(ALL_PERMISSIONS, frozenset)

    def test_document_permissions(self):
        from role_permissions import (
            PERM_DOCUMENTS_READ, PERM_DOCUMENTS_WRITE, PERM_DOCUMENTS_DELETE,
            PERM_DOCUMENTS_VISIBILITY, PERM_DOCUMENTS_VISIBILITY_ALL,
        )
        assert PERM_DOCUMENTS_READ == "documents.read"
        assert PERM_DOCUMENTS_WRITE == "documents.write"
        assert PERM_DOCUMENTS_DELETE == "documents.delete"
        assert PERM_DOCUMENTS_VISIBILITY == "documents.visibility"
        assert PERM_DOCUMENTS_VISIBILITY_ALL == "documents.visibility.all"

    def test_operational_permissions(self):
        from role_permissions import PERM_HEALTH_VIEW, PERM_AUDIT_VIEW
        assert PERM_HEALTH_VIEW == "health.view"
        assert PERM_AUDIT_VIEW == "audit.view"

    def test_management_permissions(self):
        from role_permissions import PERM_USERS_MANAGE, PERM_KEYS_MANAGE
        assert PERM_USERS_MANAGE == "users.manage"
        assert PERM_KEYS_MANAGE == "keys.manage"

    def test_system_permission(self):
        from role_permissions import PERM_SYSTEM_ADMIN
        assert PERM_SYSTEM_ADMIN == "system.admin"


# ===========================================================================
# Test: Built-in role definitions
# ===========================================================================


class TestBuiltinRoles:
    def test_admin_has_all_permissions(self):
        from role_permissions import BUILTIN_ROLES, ALL_PERMISSIONS
        admin_perms = set(BUILTIN_ROLES["admin"]["permissions"])
        assert admin_perms == ALL_PERMISSIONS

    def test_admin_is_system(self):
        from role_permissions import BUILTIN_ROLES
        assert BUILTIN_ROLES["admin"]["is_system"] is True

    def test_user_is_system(self):
        from role_permissions import BUILTIN_ROLES
        assert BUILTIN_ROLES["user"]["is_system"] is True

    def test_researcher_is_not_system(self):
        from role_permissions import BUILTIN_ROLES
        assert BUILTIN_ROLES["researcher"]["is_system"] is False

    def test_sre_has_health_and_audit(self):
        from role_permissions import BUILTIN_ROLES, PERM_HEALTH_VIEW, PERM_AUDIT_VIEW
        sre_perms = BUILTIN_ROLES["sre"]["permissions"]
        assert PERM_HEALTH_VIEW in sre_perms
        assert PERM_AUDIT_VIEW in sre_perms

    def test_support_is_read_only(self):
        from role_permissions import BUILTIN_ROLES, PERM_DOCUMENTS_WRITE, PERM_DOCUMENTS_DELETE
        support_perms = BUILTIN_ROLES["support"]["permissions"]
        assert PERM_DOCUMENTS_WRITE not in support_perms
        assert PERM_DOCUMENTS_DELETE not in support_perms

    def test_support_has_read_health_audit(self):
        from role_permissions import BUILTIN_ROLES, PERM_DOCUMENTS_READ, PERM_HEALTH_VIEW, PERM_AUDIT_VIEW
        support_perms = BUILTIN_ROLES["support"]["permissions"]
        assert PERM_DOCUMENTS_READ in support_perms
        assert PERM_HEALTH_VIEW in support_perms
        assert PERM_AUDIT_VIEW in support_perms

    def test_five_builtin_roles(self):
        from role_permissions import BUILTIN_ROLES
        assert len(BUILTIN_ROLES) == 5
        assert set(BUILTIN_ROLES.keys()) == {"admin", "user", "researcher", "sre", "support"}


# ===========================================================================
# Test: Config loading
# ===========================================================================


class TestConfigLoading:
    def test_load_defaults(self):
        import role_permissions
        role_permissions._role_config = None  # Force reload
        config = role_permissions.load_role_config(force_reload=True)
        assert "admin" in config
        assert "user" in config

    def test_config_file_exists(self):
        assert (PROJECT_ROOT / "role_permissions.json").exists()

    def test_config_file_valid_json(self):
        with open(PROJECT_ROOT / "role_permissions.json") as f:
            config = json.load(f)
        assert isinstance(config, dict)
        assert "admin" in config
        assert "user" in config

    def test_config_file_has_custom_roles(self):
        with open(PROJECT_ROOT / "role_permissions.json") as f:
            config = json.load(f)
        assert "researcher" in config
        assert "sre" in config
        assert "support" in config

    def test_load_from_custom_file(self):
        import role_permissions
        custom_config = {
            "admin": {
                "description": "Admin",
                "permissions": sorted(role_permissions.ALL_PERMISSIONS),
                "is_system": True,
            },
            "viewer": {
                "description": "View only",
                "permissions": ["documents.read"],
                "is_system": False,
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(custom_config, f)
            tmp_path = f.name

        try:
            old_config_file = role_permissions._CONFIG_FILE
            role_permissions._CONFIG_FILE = tmp_path
            role_permissions._role_config = None
            # Mock DB load to return None so it falls back to the custom file
            with patch('role_permissions._load_from_db', return_value=None):
                config = role_permissions.load_role_config(force_reload=True)
            assert "viewer" in config
            assert "admin" in config
        finally:
            role_permissions._CONFIG_FILE = old_config_file
            role_permissions._role_config = None
            role_permissions.load_role_config(force_reload=True)
            os.unlink(tmp_path)

    def test_admin_always_has_all_permissions(self):
        """Even if config file strips admin permissions, they get restored."""
        import role_permissions
        custom_config = {
            "admin": {
                "description": "Admin",
                "permissions": ["documents.read"],  # Intentionally incomplete
                "is_system": False,
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(custom_config, f)
            tmp_path = f.name

        try:
            old_config_file = role_permissions._CONFIG_FILE
            role_permissions._CONFIG_FILE = tmp_path
            role_permissions._role_config = None
            config = role_permissions.load_role_config(force_reload=True)
            assert set(config["admin"]["permissions"]) == role_permissions.ALL_PERMISSIONS
            assert config["admin"]["is_system"] is True
        finally:
            role_permissions._CONFIG_FILE = old_config_file
            role_permissions._role_config = None
            role_permissions.load_role_config(force_reload=True)
            os.unlink(tmp_path)


# ===========================================================================
# Test: Permission checks
# ===========================================================================


class TestPermissionChecks:
    def test_admin_has_all(self):
        from role_permissions import has_permission, ALL_PERMISSIONS
        for perm in ALL_PERMISSIONS:
            assert has_permission("admin", perm) is True

    def test_user_has_read(self):
        from role_permissions import has_permission, PERM_DOCUMENTS_READ
        assert has_permission("user", PERM_DOCUMENTS_READ) is True

    def test_user_lacks_delete(self):
        from role_permissions import has_permission, PERM_DOCUMENTS_DELETE
        assert has_permission("user", PERM_DOCUMENTS_DELETE) is False

    def test_user_lacks_users_manage(self):
        from role_permissions import has_permission, PERM_USERS_MANAGE
        assert has_permission("user", PERM_USERS_MANAGE) is False

    def test_sre_has_delete(self):
        from role_permissions import has_permission, PERM_DOCUMENTS_DELETE
        assert has_permission("sre", PERM_DOCUMENTS_DELETE) is True

    def test_sre_lacks_users_manage(self):
        from role_permissions import has_permission, PERM_USERS_MANAGE
        assert has_permission("sre", PERM_USERS_MANAGE) is False

    def test_support_lacks_write(self):
        from role_permissions import has_permission, PERM_DOCUMENTS_WRITE
        assert has_permission("support", PERM_DOCUMENTS_WRITE) is False

    def test_support_has_health(self):
        from role_permissions import has_permission, PERM_HEALTH_VIEW
        assert has_permission("support", PERM_HEALTH_VIEW) is True

    def test_unknown_role_has_nothing(self):
        from role_permissions import has_permission, PERM_DOCUMENTS_READ
        assert has_permission("nonexistent", PERM_DOCUMENTS_READ) is False

    def test_system_admin_grants_everything(self):
        """A role with system.admin permission should pass any check."""
        from role_permissions import has_permission, PERM_DOCUMENTS_DELETE
        # Admin has system.admin, so it should grant documents.delete
        assert has_permission("admin", PERM_DOCUMENTS_DELETE) is True


# ===========================================================================
# Test: Role validation
# ===========================================================================


class TestRoleValidation:
    def test_admin_is_valid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("admin") is True

    def test_user_is_valid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("user") is True

    def test_researcher_is_valid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("researcher") is True

    def test_sre_is_valid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("sre") is True

    def test_support_is_valid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("support") is True

    def test_unknown_is_invalid(self):
        from role_permissions import is_valid_role
        assert is_valid_role("nonexistent") is False

    def test_get_valid_roles_returns_all(self):
        from role_permissions import get_valid_roles
        roles = get_valid_roles()
        assert "admin" in roles
        assert "user" in roles
        assert "researcher" in roles
        assert "sre" in roles
        assert "support" in roles


# ===========================================================================
# Test: Role listing and info
# ===========================================================================


class TestRoleListing:
    def test_list_roles_returns_all(self):
        from role_permissions import list_roles
        roles = list_roles()
        names = [r["name"] for r in roles]
        assert "admin" in names
        assert "user" in names
        assert "researcher" in names

    def test_list_roles_sorted(self):
        from role_permissions import list_roles
        roles = list_roles()
        names = [r["name"] for r in roles]
        assert names == sorted(names)

    def test_role_info_structure(self):
        from role_permissions import get_role_info
        info = get_role_info("sre")
        assert info is not None
        assert "name" in info
        assert "description" in info
        assert "permissions" in info
        assert "is_system" in info
        assert info["name"] == "sre"

    def test_role_info_unknown(self):
        from role_permissions import get_role_info
        assert get_role_info("nonexistent") is None


# ===========================================================================
# Test: Permission listing
# ===========================================================================


class TestPermissionListing:
    def test_list_permissions_count(self):
        from role_permissions import list_permissions, ALL_PERMISSIONS
        perms = list_permissions()
        assert len(perms) == len(ALL_PERMISSIONS)

    def test_list_permissions_structure(self):
        from role_permissions import list_permissions
        perms = list_permissions()
        for p in perms:
            assert "permission" in p
            assert "description" in p
            assert isinstance(p["description"], str)

    def test_list_permissions_sorted(self):
        from role_permissions import list_permissions
        perms = list_permissions()
        names = [p["permission"] for p in perms]
        assert names == sorted(names)


# ===========================================================================
# Test: require_permission() factory
# ===========================================================================


class TestRequirePermission:
    def test_factory_returns_callable(self):
        from auth import require_permission
        checker = require_permission("documents.read")
        assert callable(checker)

    def test_require_admin_is_async(self):
        import asyncio
        from auth import require_admin
        assert asyncio.iscoroutinefunction(require_admin)

    def test_factory_result_is_async(self):
        import asyncio
        from auth import require_permission
        checker = require_permission("documents.read")
        assert asyncio.iscoroutinefunction(checker)


# ===========================================================================
# Test: users.py dynamic role validation
# ===========================================================================


class TestUsersDynamicRoles:
    def test_get_valid_roles_includes_custom(self):
        from users import _get_valid_roles
        roles = _get_valid_roles()
        assert "researcher" in roles
        assert "sre" in roles
        assert "support" in roles

    def test_get_valid_roles_includes_builtins(self):
        from users import _get_valid_roles
        roles = _get_valid_roles()
        assert "admin" in roles
        assert "user" in roles

    def test_legacy_valid_roles_still_exists(self):
        from users import VALID_ROLES
        assert "admin" in VALID_ROLES
        assert "user" in VALID_ROLES


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestRolesEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_list_roles_endpoint(self):
        assert "/api/v1/roles" in self.routes

    def test_get_role_endpoint(self):
        assert "/api/v1/roles/{role_name}" in self.routes

    def test_list_permissions_endpoint(self):
        assert "/api/v1/permissions" in self.routes

    def test_check_permission_endpoint(self):
        assert "/api/v1/roles/{role_name}/check/{permission}" in self.routes
