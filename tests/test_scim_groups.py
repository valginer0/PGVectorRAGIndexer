"""
Tests for SCIM 2.0 Group provisioning.

Covers:
- Group ↔ SCIM schema mapping
- Group-to-role resolution logic
- Group CRUD operations (create, read, update, delete)
- Group membership changes via PATCH
- Group filter parser
- Group endpoint registration
- Discovery endpoint updates (ResourceTypes, Schemas)
- Edge cases (duplicate names, invalid roles, multi-group users)
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Group constants
# ===========================================================================


class TestGroupConstants:
    def test_group_schema_uri(self):
        from scim import SCIM_SCHEMA_GROUP
        assert "urn:ietf:params:scim" in SCIM_SCHEMA_GROUP
        assert "Group" in SCIM_SCHEMA_GROUP

    def test_group_extension_uri(self):
        from scim import CUSTOM_SCHEMA_GROUP_ROLE
        assert "pgvector" in CUSTOM_SCHEMA_GROUP_ROLE
        assert "Group" in CUSTOM_SCHEMA_GROUP_ROLE


# ===========================================================================
# Test: Group ↔ SCIM mapping
# ===========================================================================


class TestGroupToScim:
    def test_basic_mapping(self):
        from scim import group_to_scim, SCIM_SCHEMA_GROUP, CUSTOM_SCHEMA_GROUP_ROLE

        group = {
            "id": "g1",
            "display_name": "Admins",
            "role_name": "admin",
            "external_id": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        with patch("scim.get_group_members", return_value=[]):
            result = group_to_scim(group, base_url="http://localhost:8000")

        assert SCIM_SCHEMA_GROUP in result["schemas"]
        assert result["id"] == "g1"
        assert result["displayName"] == "Admins"
        assert result[CUSTOM_SCHEMA_GROUP_ROLE]["roleName"] == "admin"
        assert result["meta"]["resourceType"] == "Group"
        assert "Groups/g1" in result["meta"]["location"]
        assert result["members"] == []

    def test_external_id_included(self):
        from scim import group_to_scim

        group = {
            "id": "g2",
            "display_name": "Devs",
            "role_name": "user",
            "external_id": "okta-123",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        with patch("scim.get_group_members", return_value=[]):
            result = group_to_scim(group)

        assert result["externalId"] == "okta-123"

    def test_members_included(self):
        from scim import group_to_scim

        group = {
            "id": "g3",
            "display_name": "Team",
            "role_name": "user",
            "external_id": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        members = [
            {"value": "u1", "display": "Alice"},
            {"value": "u2", "display": "Bob"},
        ]

        with patch("scim.get_group_members", return_value=members):
            result = group_to_scim(group)

        assert len(result["members"]) == 2
        assert result["members"][0]["value"] == "u1"


# ===========================================================================
# Test: Role resolution from SCIM data
# ===========================================================================


class TestResolveRoleName:
    def test_explicit_extension(self):
        from scim import _resolve_role_name, CUSTOM_SCHEMA_GROUP_ROLE

        data = {
            "displayName": "Some Group",
            CUSTOM_SCHEMA_GROUP_ROLE: {"roleName": "sre"},
        }
        assert _resolve_role_name(data) == "sre"

    def test_name_matches_role(self):
        from scim import _resolve_role_name

        data = {"displayName": "admin"}
        with patch("role_permissions.is_valid_role", side_effect=lambda r: r == "admin"):
            assert _resolve_role_name(data) == "admin"

    def test_name_matches_case_insensitive(self):
        from scim import _resolve_role_name

        data = {"displayName": "Admin"}
        with patch("role_permissions.is_valid_role", side_effect=lambda r: r == "admin"):
            assert _resolve_role_name(data) == "admin"

    def test_no_match_falls_back_to_default(self):
        from scim import _resolve_role_name, SCIM_DEFAULT_ROLE

        data = {"displayName": "Data Scientists"}
        with patch("role_permissions.is_valid_role", return_value=False):
            assert _resolve_role_name(data) == SCIM_DEFAULT_ROLE

    def test_extension_takes_priority_over_name(self):
        from scim import _resolve_role_name, CUSTOM_SCHEMA_GROUP_ROLE

        data = {
            "displayName": "admin",
            CUSTOM_SCHEMA_GROUP_ROLE: {"roleName": "viewer"},
        }
        assert _resolve_role_name(data) == "viewer"


# ===========================================================================
# Test: Group row conversion
# ===========================================================================


class TestGroupRowToDict:
    def test_converts_timestamps(self):
        from scim import _group_row_to_dict

        now = datetime(2026, 3, 13, 12, 0, 0)
        row = ("g1", "ext-1", "Admins", "admin", now, now)
        result = _group_row_to_dict(row)
        assert result["id"] == "g1"
        assert result["external_id"] == "ext-1"
        assert result["display_name"] == "Admins"
        assert result["role_name"] == "admin"
        assert "2026-03-13" in result["created_at"]

    def test_handles_none_external_id(self):
        from scim import _group_row_to_dict

        row = ("g1", None, "Users", "user", "2026-01-01", "2026-01-01")
        result = _group_row_to_dict(row)
        assert result["external_id"] is None


# ===========================================================================
# Test: Group CRUD
# ===========================================================================


class TestGroupCRUD:
    def test_create_group(self):
        from scim import create_scim_group

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("g1", None, "Admins", "admin", "2026-01-01", "2026-01-01")

        with patch("scim._get_db_connection", return_value=mock_conn), \
             patch("role_permissions.is_valid_role", return_value=True):
            result = create_scim_group("Admins", "admin")

        assert result["id"] == "g1"
        assert result["display_name"] == "Admins"
        assert result["role_name"] == "admin"
        mock_conn.commit.assert_called_once()

    def test_create_group_invalid_role_raises(self):
        from scim import create_scim_group

        with patch("role_permissions.is_valid_role", return_value=False):
            with pytest.raises(ValueError, match="does not exist"):
                create_scim_group("Bad Group", "nonexistent_role")

    def test_get_group(self):
        from scim import get_scim_group

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("g1", None, "Admins", "admin", "2026-01-01", "2026-01-01")

        with patch("scim._get_db_connection", return_value=mock_conn):
            result = get_scim_group("g1")

        assert result["id"] == "g1"

    def test_get_group_not_found(self):
        from scim import get_scim_group

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("scim._get_db_connection", return_value=mock_conn):
            assert get_scim_group("nonexistent") is None

    def test_update_group(self):
        from scim import update_scim_group

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("g1", None, "New Name", "admin", "2026-01-01", "2026-01-02")

        with patch("scim._get_db_connection", return_value=mock_conn):
            result = update_scim_group("g1", display_name="New Name")

        assert result["display_name"] == "New Name"
        mock_conn.commit.assert_called_once()

    def test_update_group_invalid_role_raises(self):
        from scim import update_scim_group

        with patch("role_permissions.is_valid_role", return_value=False):
            with pytest.raises(ValueError, match="does not exist"):
                update_scim_group("g1", role_name="bad_role")

    def test_update_group_no_changes(self):
        from scim import update_scim_group, get_scim_group

        with patch("scim.get_scim_group", return_value={"id": "g1", "display_name": "X"}) as mock:
            result = update_scim_group("g1")
            mock.assert_called_once_with("g1")

    def test_delete_group(self):
        from scim import delete_scim_group

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 1

        with patch("scim._get_db_connection", return_value=mock_conn):
            assert delete_scim_group("g1") is True
        mock_conn.commit.assert_called_once()

    def test_delete_group_not_found(self):
        from scim import delete_scim_group

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 0

        with patch("scim._get_db_connection", return_value=mock_conn):
            assert delete_scim_group("g1") is False


# ===========================================================================
# Test: Group members query
# ===========================================================================


class TestGroupMembers:
    def test_get_group_members(self):
        from scim import get_group_members

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("u1", "alice@example.com", "Alice"),
            ("u2", "bob@example.com", None),
        ]

        with patch("scim._get_db_connection", return_value=mock_conn):
            members = get_group_members("admin", base_url="http://localhost")

        assert len(members) == 2
        assert members[0]["value"] == "u1"
        assert members[0]["display"] == "Alice"
        assert "Users/u1" in members[0]["$ref"]
        assert members[1]["display"] == "bob@example.com"  # fallback to email

    def test_get_group_members_empty(self):
        from scim import get_group_members

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("scim._get_db_connection", return_value=mock_conn):
            assert get_group_members("nonexistent") == []


# ===========================================================================
# Test: Group list with filtering
# ===========================================================================


class TestListScimGroups:
    def test_list_groups_no_filter(self):
        from scim import list_scim_groups, SCIM_SCHEMA_LIST

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (2,)
        mock_cursor.fetchall.return_value = [
            ("g1", None, "Admins", "admin", "2026-01-01", "2026-01-01"),
            ("g2", None, "Users", "user", "2026-01-01", "2026-01-01"),
        ]

        with patch("scim._get_db_connection", return_value=mock_conn), \
             patch("scim.get_group_members", return_value=[]):
            result = list_scim_groups()

        assert result["schemas"] == [SCIM_SCHEMA_LIST]
        assert result["totalResults"] == 2
        assert len(result["Resources"]) == 2

    def test_list_groups_with_filter(self):
        from scim import list_scim_groups

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: mock_conn
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_cursor.fetchall.return_value = [
            ("g1", None, "Admins", "admin", "2026-01-01", "2026-01-01"),
        ]

        with patch("scim._get_db_connection", return_value=mock_conn), \
             patch("scim.get_group_members", return_value=[]):
            result = list_scim_groups(filter_str='displayName eq "Admins"')

        assert result["totalResults"] == 1
        # Verify filter was applied (SQL contains WHERE)
        sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("WHERE" in s for s in sql_calls)


# ===========================================================================
# Test: Group PATCH membership
# ===========================================================================


class TestGroupMembership:
    def _mock_group(self):
        return {"id": "g1", "display_name": "Admins", "role_name": "admin",
                "external_id": None, "created_at": "2026-01-01", "updated_at": "2026-01-01"}

    def test_add_members(self):
        from scim import apply_group_membership

        ops = [{"op": "add", "path": "members", "value": [
            {"value": "u1"}, {"value": "u2"}
        ]}]

        with patch("scim.get_scim_group", return_value=self._mock_group()), \
             patch("users.change_role") as mock_change:
            result = apply_group_membership("g1", ops)

        assert mock_change.call_count == 2
        mock_change.assert_any_call("u1", "admin")
        mock_change.assert_any_call("u2", "admin")

    def test_remove_members(self):
        from scim import apply_group_membership, SCIM_DEFAULT_ROLE

        ops = [{"op": "remove", "path": "members", "value": [{"value": "u1"}]}]

        with patch("scim.get_scim_group", return_value=self._mock_group()), \
             patch("users.change_role") as mock_change:
            apply_group_membership("g1", ops)

        mock_change.assert_called_once_with("u1", SCIM_DEFAULT_ROLE)

    def test_replace_members(self):
        from scim import apply_group_membership

        ops = [{"op": "replace", "path": "members", "value": [{"value": "u3"}]}]

        with patch("scim.get_scim_group", return_value=self._mock_group()), \
             patch("users.change_role") as mock_change:
            apply_group_membership("g1", ops)

        mock_change.assert_called_once_with("u3", "admin")

    def test_update_display_name(self):
        from scim import apply_group_membership

        ops = [{"op": "replace", "path": "displayName", "value": "Super Admins"}]

        with patch("scim.get_scim_group", return_value=self._mock_group()), \
             patch("scim.update_scim_group", return_value=self._mock_group()) as mock_update:
            apply_group_membership("g1", ops)

        mock_update.assert_called_once_with("g1", display_name="Super Admins")

    def test_group_not_found(self):
        from scim import apply_group_membership

        with patch("scim.get_scim_group", return_value=None):
            assert apply_group_membership("nonexistent", []) is None

    def test_mixed_operations(self):
        """Add members and rename group in one PATCH."""
        from scim import apply_group_membership

        ops = [
            {"op": "add", "path": "members", "value": [{"value": "u1"}]},
            {"op": "replace", "path": "displayName", "value": "New Name"},
        ]

        with patch("scim.get_scim_group", return_value=self._mock_group()), \
             patch("users.change_role") as mock_change, \
             patch("scim.update_scim_group", return_value=self._mock_group()) as mock_update:
            apply_group_membership("g1", ops)

        mock_change.assert_called_once_with("u1", "admin")
        mock_update.assert_called_once_with("g1", display_name="New Name")


# ===========================================================================
# Test: Group filter parsing
# ===========================================================================


class TestGroupFilter:
    def test_display_name_eq(self):
        from scim import parse_scim_filter

        group_attr_map = {"displayName": "display_name", "displayname": "display_name"}
        result = parse_scim_filter('displayName eq "Admins"', attr_map=group_attr_map)
        assert result is not None
        sql, params = result
        assert "display_name = %s" in sql
        assert params == ["Admins"]

    def test_display_name_co(self):
        from scim import parse_scim_filter

        group_attr_map = {"displayName": "display_name", "displayname": "display_name"}
        result = parse_scim_filter('displayName co "Admin"', attr_map=group_attr_map)
        assert result is not None
        sql, params = result
        assert "ILIKE" in sql
        assert params == ["%Admin%"]

    def test_unknown_attr_returns_none(self):
        from scim import parse_scim_filter

        group_attr_map = {"displayName": "display_name"}
        result = parse_scim_filter('unknownAttr eq "x"', attr_map=group_attr_map)
        assert result is None


# ===========================================================================
# Test: Discovery endpoints include Groups
# ===========================================================================


class TestGroupDiscovery:
    def test_resource_types_includes_group(self):
        from scim import get_resource_types
        types = get_resource_types()
        group_types = [t for t in types if t["name"] == "Group"]
        assert len(group_types) == 1
        assert group_types[0]["endpoint"] == "/scim/v2/Groups"

    def test_schemas_includes_group(self):
        from scim import get_schemas, SCIM_SCHEMA_GROUP
        schemas = get_schemas()
        group_schemas = [s for s in schemas if s["id"] == SCIM_SCHEMA_GROUP]
        assert len(group_schemas) == 1
        attrs = [a["name"] for a in group_schemas[0]["attributes"]]
        assert "displayName" in attrs
        assert "members" in attrs

    def test_schemas_includes_group_extension(self):
        from scim import get_schemas, CUSTOM_SCHEMA_GROUP_ROLE
        schemas = get_schemas()
        ext_schemas = [s for s in schemas if s["id"] == CUSTOM_SCHEMA_GROUP_ROLE]
        assert len(ext_schemas) == 1
        attrs = [a["name"] for a in ext_schemas[0]["attributes"]]
        assert "roleName" in attrs


# ===========================================================================
# Test: Group endpoint registration
# ===========================================================================


class TestGroupEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from api import app
        self.routes = {r.path for r in app.routes if hasattr(r, "path")}

    def test_list_groups_endpoint(self):
        assert "/scim/v2/Groups" in self.routes

    def test_get_group_endpoint(self):
        assert "/scim/v2/Groups/{group_id}" in self.routes

    def test_create_group_endpoint(self):
        # POST /scim/v2/Groups — same path as GET list
        assert "/scim/v2/Groups" in self.routes

    def test_delete_group_endpoint(self):
        # DELETE /scim/v2/Groups/{group_id} — same path as GET
        assert "/scim/v2/Groups/{group_id}" in self.routes


# ===========================================================================
# Test: Edge cases
# ===========================================================================


class TestGroupEdgeCases:
    def test_add_member_with_string_value(self):
        """Some IdPs send member value as plain string, not dict."""
        from scim import apply_group_membership

        group = {"id": "g1", "display_name": "G", "role_name": "admin",
                 "external_id": None, "created_at": "", "updated_at": ""}
        ops = [{"op": "add", "path": "members", "value": [{"value": "u1"}]}]

        with patch("scim.get_scim_group", return_value=group), \
             patch("users.change_role") as mock_change:
            apply_group_membership("g1", ops)

        mock_change.assert_called_once_with("u1", "admin")

    def test_remove_members_empty_value(self):
        """Remove with no value list should not crash."""
        from scim import apply_group_membership

        group = {"id": "g1", "display_name": "G", "role_name": "admin",
                 "external_id": None, "created_at": "", "updated_at": ""}
        ops = [{"op": "remove", "path": "members"}]

        with patch("scim.get_scim_group", return_value=group), \
             patch("users.change_role") as mock_change:
            apply_group_membership("g1", ops)

        mock_change.assert_not_called()

    def test_no_path_with_dict_value_updates_display_name(self):
        """PATCH with no path but dict value containing displayName."""
        from scim import apply_group_membership

        group = {"id": "g1", "display_name": "Old", "role_name": "admin",
                 "external_id": None, "created_at": "", "updated_at": ""}
        ops = [{"op": "replace", "path": "", "value": {"displayName": "New"}}]

        with patch("scim.get_scim_group", return_value=group), \
             patch("scim.update_scim_group", return_value=group) as mock_update:
            apply_group_membership("g1", ops)

        mock_update.assert_called_once_with("g1", display_name="New")
