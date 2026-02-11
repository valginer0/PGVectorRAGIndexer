"""
Tests for #16 Enterprise Foundations Phase 3 — SCIM 2.0 Provisioning.

Tests cover:
- Configuration and availability
- Bearer token validation
- User ↔ SCIM schema mapping
- SCIM filter parser
- SCIM PATCH operation processor
- SCIM error builder
- Discovery endpoints (ServiceProviderConfig, Schemas, ResourceTypes)
- SCIM CRUD endpoint registration
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Configuration
# ===========================================================================


class TestScimConfig:
    def test_scim_disabled_by_default(self):
        from scim import SCIM_ENABLED
        if os.environ.get("SCIM_ENABLED", "").lower() not in ("true", "1", "yes"):
            assert SCIM_ENABLED is False

    def test_is_scim_available_requires_both(self):
        from scim import is_scim_available, SCIM_ENABLED, SCIM_BEARER_TOKEN
        result = is_scim_available()
        assert result == (SCIM_ENABLED and bool(SCIM_BEARER_TOKEN))

    def test_default_role(self):
        from scim import SCIM_DEFAULT_ROLE
        if "SCIM_DEFAULT_ROLE" not in os.environ:
            assert SCIM_DEFAULT_ROLE == "user"


# ===========================================================================
# Test: Bearer token validation
# ===========================================================================


class TestBearerTokenValidation:
    def test_valid_token(self):
        from scim import validate_bearer_token, SCIM_BEARER_TOKEN
        if SCIM_BEARER_TOKEN:
            assert validate_bearer_token(f"Bearer {SCIM_BEARER_TOKEN}") is True

    def test_missing_header(self):
        from scim import validate_bearer_token
        assert validate_bearer_token(None) is False
        assert validate_bearer_token("") is False

    def test_wrong_scheme(self):
        from scim import validate_bearer_token
        assert validate_bearer_token("Basic abc123") is False

    def test_wrong_token(self):
        from scim import validate_bearer_token
        assert validate_bearer_token("Bearer wrong_token_value_xyz") is False

    def test_no_space(self):
        from scim import validate_bearer_token
        assert validate_bearer_token("Bearertoken") is False


# ===========================================================================
# Test: User → SCIM mapping
# ===========================================================================


class TestUserToScim:
    def test_basic_mapping(self):
        from scim import user_to_scim, SCIM_SCHEMA_USER, CUSTOM_SCHEMA_ROLE
        user = {
            "id": "u1",
            "email": "alice@example.com",
            "display_name": "Alice Smith",
            "role": "admin",
            "is_active": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00",
        }
        scim = user_to_scim(user)
        assert scim["id"] == "u1"
        assert scim["userName"] == "alice@example.com"
        assert scim["displayName"] == "Alice Smith"
        assert scim["active"] is True
        assert SCIM_SCHEMA_USER in scim["schemas"]
        assert CUSTOM_SCHEMA_ROLE in scim["schemas"]
        assert scim[CUSTOM_SCHEMA_ROLE]["role"] == "admin"
        assert len(scim["emails"]) == 1
        assert scim["emails"][0]["value"] == "alice@example.com"
        assert scim["emails"][0]["primary"] is True

    def test_no_email(self):
        from scim import user_to_scim
        user = {"id": "u2", "email": None, "display_name": None, "role": "user",
                "is_active": True, "created_at": "", "updated_at": ""}
        scim = user_to_scim(user)
        assert scim["emails"] == []
        assert scim["userName"] == ""

    def test_location_with_base_url(self):
        from scim import user_to_scim
        user = {"id": "u3", "email": "bob@example.com", "display_name": "Bob",
                "role": "user", "is_active": True, "created_at": "", "updated_at": ""}
        scim = user_to_scim(user, base_url="https://app.example.com")
        assert scim["meta"]["location"] == "https://app.example.com/scim/v2/Users/u3"

    def test_no_location_without_base_url(self):
        from scim import user_to_scim
        user = {"id": "u4", "email": "c@d.com", "display_name": "", "role": "user",
                "is_active": True, "created_at": "", "updated_at": ""}
        scim = user_to_scim(user)
        assert "location" not in scim["meta"]


# ===========================================================================
# Test: SCIM → User mapping
# ===========================================================================


class TestScimToUserParams:
    def test_username_maps_to_email(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({"userName": "alice@example.com"})
        assert params["email"] == "alice@example.com"

    def test_display_name(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({"displayName": "Alice Smith"})
        assert params["display_name"] == "Alice Smith"

    def test_emails_primary(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({
            "userName": "old@example.com",
            "emails": [
                {"value": "primary@example.com", "primary": True, "type": "work"},
                {"value": "secondary@example.com", "type": "home"},
            ],
        })
        # emails[0].primary takes precedence over userName
        assert params["email"] == "primary@example.com"

    def test_emails_first_fallback(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({
            "emails": [{"value": "first@example.com", "type": "work"}],
        })
        assert params["email"] == "first@example.com"

    def test_active_mapping(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({"active": False})
        assert params["is_active"] is False

    def test_custom_role_extension(self):
        from scim import scim_to_user_params, CUSTOM_SCHEMA_ROLE
        params = scim_to_user_params({CUSTOM_SCHEMA_ROLE: {"role": "admin"}})
        assert params["role"] == "admin"

    def test_name_formatted(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({"name": {"formatted": "Dr. Alice Smith"}})
        assert params["display_name"] == "Dr. Alice Smith"

    def test_name_given_family(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({"name": {"givenName": "Alice", "familyName": "Smith"}})
        assert params["display_name"] == "Alice Smith"

    def test_empty_input(self):
        from scim import scim_to_user_params
        params = scim_to_user_params({})
        assert params == {}


# ===========================================================================
# Test: SCIM error builder
# ===========================================================================


class TestScimError:
    def test_basic_error(self):
        from scim import scim_error, SCIM_SCHEMA_ERROR
        err = scim_error(404, "Not found")
        assert err["status"] == "404"
        assert err["detail"] == "Not found"
        assert SCIM_SCHEMA_ERROR in err["schemas"]
        assert "scimType" not in err

    def test_error_with_type(self):
        from scim import scim_error
        err = scim_error(409, "Duplicate", "uniqueness")
        assert err["scimType"] == "uniqueness"


# ===========================================================================
# Test: SCIM filter parser
# ===========================================================================


class TestScimFilterParser:
    def test_simple_eq(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('userName eq "alice@example.com"')
        assert result is not None
        sql, params = result
        assert "email = %s" in sql
        assert "alice@example.com" in params

    def test_display_name_eq(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('displayName eq "Alice"')
        assert result is not None
        sql, params = result
        assert "display_name = %s" in sql

    def test_contains(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('userName co "example"')
        assert result is not None
        sql, params = result
        assert "ILIKE" in sql
        assert "%example%" in params

    def test_starts_with(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('userName sw "alice"')
        assert result is not None
        sql, params = result
        assert "ILIKE" in sql
        assert "alice%" in params

    def test_ends_with(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('userName ew "example.com"')
        assert result is not None
        sql, params = result
        assert "%example.com" in params

    def test_and_filter(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('userName eq "alice@example.com" and active eq "true"')
        assert result is not None
        sql, params = result
        assert "AND" in sql
        assert len(params) == 2

    def test_active_boolean_conversion(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('active eq "true"')
        assert result is not None
        sql, params = result
        assert params[0] is True

    def test_emails_value(self):
        from scim import parse_scim_filter
        result = parse_scim_filter('emails.value eq "test@example.com"')
        assert result is not None
        sql, params = result
        assert "email = %s" in sql

    def test_empty_filter(self):
        from scim import parse_scim_filter
        assert parse_scim_filter("") is None
        assert parse_scim_filter(None) is None

    def test_unknown_attribute(self):
        from scim import parse_scim_filter
        assert parse_scim_filter('unknownAttr eq "value"') is None


# ===========================================================================
# Test: SCIM PATCH operations
# ===========================================================================


class TestScimPatchOperations:
    @patch("users.get_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": True})
    @patch("users.update_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "New Name", "role": "user", "is_active": True})
    def test_replace_display_name(self, mock_update, mock_get):
        from scim import apply_patch_operations
        result = apply_patch_operations("u1", [
            {"op": "replace", "path": "displayName", "value": "New Name"}
        ])
        assert result is not None
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        assert call_kwargs[1].get("display_name") == "New Name" or \
               (len(call_kwargs[0]) > 1 and "display_name" in str(call_kwargs))

    @patch("users.get_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": True})
    @patch("users.update_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": False})
    def test_replace_active(self, mock_update, mock_get):
        from scim import apply_patch_operations
        result = apply_patch_operations("u1", [
            {"op": "replace", "path": "active", "value": False}
        ])
        assert result is not None

    @patch("users.get_user", return_value=None)
    def test_patch_nonexistent_user(self, mock_get):
        from scim import apply_patch_operations
        result = apply_patch_operations("nonexistent", [
            {"op": "replace", "path": "active", "value": False}
        ])
        assert result is None

    @patch("users.get_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": True})
    def test_empty_operations_returns_current(self, mock_get):
        from scim import apply_patch_operations
        result = apply_patch_operations("u1", [])
        assert result is not None
        assert result["id"] == "u1"

    @patch("users.get_user", return_value={"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": True})
    @patch("users.update_user", return_value={"id": "u1", "email": "new@b.com", "display_name": "A", "role": "user", "is_active": True})
    def test_replace_no_path_with_dict(self, mock_update, mock_get):
        from scim import apply_patch_operations
        result = apply_patch_operations("u1", [
            {"op": "replace", "value": {"userName": "new@b.com"}}
        ])
        assert result is not None


# ===========================================================================
# Test: Discovery endpoints (static)
# ===========================================================================


class TestScimDiscovery:
    def test_service_provider_config(self):
        from scim import get_service_provider_config, SCIM_SCHEMA_SP_CONFIG
        config = get_service_provider_config()
        assert SCIM_SCHEMA_SP_CONFIG in config["schemas"]
        assert config["patch"]["supported"] is True
        assert config["filter"]["supported"] is True
        assert config["bulk"]["supported"] is False

    def test_resource_types(self):
        from scim import get_resource_types
        types = get_resource_types()
        assert len(types) == 1
        assert types[0]["name"] == "User"
        assert types[0]["endpoint"] == "/scim/v2/Users"

    def test_schemas(self):
        from scim import get_schemas, SCIM_SCHEMA_USER, CUSTOM_SCHEMA_ROLE
        schemas = get_schemas()
        assert len(schemas) == 2
        ids = [s["id"] for s in schemas]
        assert SCIM_SCHEMA_USER in ids
        assert CUSTOM_SCHEMA_ROLE in ids

    def test_user_schema_attributes(self):
        from scim import get_schemas, SCIM_SCHEMA_USER
        schemas = get_schemas()
        user_schema = next(s for s in schemas if s["id"] == SCIM_SCHEMA_USER)
        attr_names = [a["name"] for a in user_schema["attributes"]]
        assert "userName" in attr_names
        assert "displayName" in attr_names
        assert "emails" in attr_names
        assert "active" in attr_names


# ===========================================================================
# Test: SCIM constants
# ===========================================================================


class TestScimConstants:
    def test_schema_uris(self):
        from scim import (
            SCIM_SCHEMA_USER, SCIM_SCHEMA_LIST, SCIM_SCHEMA_ERROR,
            SCIM_SCHEMA_PATCH, SCIM_SCHEMA_SP_CONFIG, CUSTOM_SCHEMA_ROLE,
        )
        assert "urn:ietf:params:scim" in SCIM_SCHEMA_USER
        assert "ListResponse" in SCIM_SCHEMA_LIST
        assert "Error" in SCIM_SCHEMA_ERROR
        assert "PatchOp" in SCIM_SCHEMA_PATCH
        assert "ServiceProviderConfig" in SCIM_SCHEMA_SP_CONFIG
        assert "pgvector" in CUSTOM_SCHEMA_ROLE


# ===========================================================================
# Test: API endpoint registration
# ===========================================================================


class TestScimEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_service_provider_config_endpoint(self):
        assert "/scim/v2/ServiceProviderConfig" in self.routes

    def test_schemas_endpoint(self):
        assert "/scim/v2/Schemas" in self.routes

    def test_resource_types_endpoint(self):
        assert "/scim/v2/ResourceTypes" in self.routes

    def test_list_users_endpoint(self):
        assert "/scim/v2/Users" in self.routes

    def test_get_user_endpoint(self):
        assert "/scim/v2/Users/{user_id}" in self.routes

    def test_create_user_endpoint(self):
        # POST /scim/v2/Users — same path as GET list
        assert "/scim/v2/Users" in self.routes

    def test_delete_user_endpoint(self):
        # DELETE /scim/v2/Users/{user_id} — same path as GET
        assert "/scim/v2/Users/{user_id}" in self.routes
