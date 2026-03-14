"""
SCIM 2.0 provisioning server for #16 Enterprise Foundations Phase 3.

Implements RFC 7643 (SCIM Core Schema) and RFC 7644 (SCIM Protocol)
for automated user provisioning/deprovisioning from identity providers
like Okta, Azure AD, OneLogin, etc.

Endpoints:
    GET    /scim/v2/ServiceProviderConfig
    GET    /scim/v2/Schemas
    GET    /scim/v2/ResourceTypes
    GET    /scim/v2/Users
    GET    /scim/v2/Users/{id}
    POST   /scim/v2/Users
    PUT    /scim/v2/Users/{id}
    PATCH  /scim/v2/Users/{id}
    DELETE /scim/v2/Users/{id}

Configuration via environment variables:
    SCIM_ENABLED        — Enable SCIM endpoints (default: false)
    SCIM_BEARER_TOKEN   — Bearer token for SCIM API authentication (required)
    SCIM_DEFAULT_ROLE   — Default role for provisioned users (default: 'user')

Schema mapping:
    SCIM userName       → users.email
    SCIM displayName    → users.display_name
    SCIM emails[0]      → users.email
    SCIM active         → users.is_active
    SCIM x-role         → users.role (custom extension)
    SCIM meta.created   → users.created_at
    SCIM meta.lastModified → users.updated_at
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCIM_ENABLED = os.environ.get("SCIM_ENABLED", "false").lower() in ("true", "1", "yes")
SCIM_BEARER_TOKEN = os.environ.get("SCIM_BEARER_TOKEN", "")
SCIM_DEFAULT_ROLE = os.environ.get("SCIM_DEFAULT_ROLE", "user")

# SCIM constants
SCIM_SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_SCHEMA_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_SCHEMA_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_SCHEMA_SP_CONFIG = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
SCIM_SCHEMA_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCIM_SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"

CUSTOM_SCHEMA_ROLE = "urn:ietf:params:scim:schemas:extension:pgvector:2.0:User"
SCIM_SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
CUSTOM_SCHEMA_GROUP_ROLE = "urn:ietf:params:scim:schemas:extension:pgvector:2.0:Group"


def is_scim_available() -> bool:
    """Check if SCIM provisioning is enabled and configured."""
    return SCIM_ENABLED and bool(SCIM_BEARER_TOKEN)


# ---------------------------------------------------------------------------
# Bearer token validation
# ---------------------------------------------------------------------------


def validate_bearer_token(authorization: Optional[str]) -> bool:
    """Validate the Authorization header contains the correct bearer token."""
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return parts[1] == SCIM_BEARER_TOKEN


# ---------------------------------------------------------------------------
# SCIM ↔ internal user mapping
# ---------------------------------------------------------------------------


def user_to_scim(user: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    """Convert an internal user dict to a SCIM 2.0 User resource."""
    scim_user: Dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_USER, CUSTOM_SCHEMA_ROLE],
        "id": user["id"],
        "userName": user.get("email") or "",
        "displayName": user.get("display_name") or "",
        "active": user.get("is_active", True),
        "emails": [],
        "meta": {
            "resourceType": "User",
            "created": user.get("created_at", ""),
            "lastModified": user.get("updated_at", ""),
        },
        CUSTOM_SCHEMA_ROLE: {
            "role": user.get("role", "user"),
        },
    }

    if user.get("email"):
        scim_user["emails"] = [
            {"value": user["email"], "primary": True, "type": "work"}
        ]

    if base_url:
        scim_user["meta"]["location"] = f"{base_url}/scim/v2/Users/{user['id']}"

    return scim_user


def scim_to_user_params(scim_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract internal user parameters from a SCIM User resource.

    Returns a dict suitable for passing to users.create_user() or
    users.update_user() as keyword arguments.
    """
    params: Dict[str, Any] = {}

    # userName → email
    if "userName" in scim_data:
        params["email"] = scim_data["userName"]

    # displayName
    if "displayName" in scim_data:
        params["display_name"] = scim_data["displayName"]

    # emails[0].value → email (takes precedence over userName if present)
    emails = scim_data.get("emails", [])
    if emails:
        # Find primary email, or use first
        primary = next((e for e in emails if e.get("primary")), emails[0])
        if "value" in primary:
            params["email"] = primary["value"]

    # active → is_active
    if "active" in scim_data:
        params["is_active"] = bool(scim_data["active"])

    # Custom extension: role
    ext = scim_data.get(CUSTOM_SCHEMA_ROLE, {})
    if "role" in ext:
        params["role"] = ext["role"]

    # name.formatted or name.givenName + name.familyName → display_name
    name = scim_data.get("name", {})
    if name:
        if "formatted" in name:
            params["display_name"] = name["formatted"]
        elif "givenName" in name or "familyName" in name:
            parts = [name.get("givenName", ""), name.get("familyName", "")]
            params["display_name"] = " ".join(p for p in parts if p)

    return params


# ---------------------------------------------------------------------------
# SCIM error response builder
# ---------------------------------------------------------------------------


def scim_error(status: int, detail: str, scim_type: str = "") -> Dict[str, Any]:
    """Build a SCIM error response body."""
    err: Dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_ERROR],
        "detail": detail,
        "status": str(status),
    }
    if scim_type:
        err["scimType"] = scim_type
    return err


# ---------------------------------------------------------------------------
# SCIM filter parser (subset: eq, co, sw, and, or)
# ---------------------------------------------------------------------------


_USER_ATTR_MAP = {
    "userName": "email",
    "username": "email",
    "displayName": "display_name",
    "displayname": "display_name",
    "emails.value": "email",
    "active": "is_active",
    "id": "id",
    "externalId": "id",
    "externalid": "id",
    "meta.created": "created_at",
    "meta.lastModified": "updated_at",
}


def parse_scim_filter(
    filter_str: str, attr_map: Optional[Dict[str, str]] = None
) -> Optional[Tuple[str, list]]:
    """Parse a SCIM filter string into a SQL WHERE clause and params.

    Supports a practical subset of SCIM filtering:
    - Simple comparisons: attr eq "value", attr co "value", attr sw "value"
    - Boolean: and, or
    - Nested attributes: emails.value, name.givenName

    Args:
        filter_str: SCIM filter expression.
        attr_map: Attribute-to-column mapping. Defaults to User attributes.

    Returns (sql_fragment, params) or None if unparseable.
    """
    if not filter_str or not filter_str.strip():
        return None

    if attr_map is None:
        attr_map = _USER_ATTR_MAP

    # Tokenize: split on 'and' / 'or' while preserving quoted strings
    # Pattern: attr op "value" (and|or attr op "value")*
    token_pattern = re.compile(
        r'(\w[\w.]*)\s+(eq|ne|co|sw|ew|gt|ge|lt|le)\s+"([^"]*)"',
        re.IGNORECASE,
    )

    # Split on ' and ' / ' or '
    parts = re.split(r'\s+(and|or)\s+', filter_str.strip(), flags=re.IGNORECASE)

    clauses = []
    params = []
    conjunctions = []

    i = 0
    while i < len(parts):
        part = parts[i].strip()
        match = token_pattern.match(part)
        if match:
            attr, op, value = match.group(1), match.group(2).lower(), match.group(3)
            col = attr_map.get(attr) or attr_map.get(attr.lower())
            if not col:
                return None  # Unknown attribute

            if op == "eq":
                if col == "is_active":
                    clauses.append(f"{col} = %s")
                    params.append(value.lower() in ("true", "1", "yes"))
                else:
                    clauses.append(f"{col} = %s")
                    params.append(value)
            elif op == "ne":
                clauses.append(f"{col} != %s")
                params.append(value)
            elif op == "co":
                clauses.append(f"{col} ILIKE %s")
                params.append(f"%{value}%")
            elif op == "sw":
                clauses.append(f"{col} ILIKE %s")
                params.append(f"{value}%")
            elif op == "ew":
                clauses.append(f"{col} ILIKE %s")
                params.append(f"%{value}")
            else:
                return None  # Unsupported operator
        else:
            # This might be a conjunction (and/or)
            if part.lower() in ("and", "or"):
                conjunctions.append(part.upper())
            else:
                return None  # Unparseable
        i += 1

    if not clauses:
        return None

    # Build combined SQL
    sql_parts = [clauses[0]]
    for j, conj in enumerate(conjunctions):
        if j + 1 < len(clauses):
            sql_parts.append(conj)
            sql_parts.append(clauses[j + 1])

    return " ".join(sql_parts), params


# ---------------------------------------------------------------------------
# SCIM PATCH operation processor
# ---------------------------------------------------------------------------


def apply_patch_operations(
    user_id: str, operations: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Apply SCIM PATCH operations to a user.

    Supports:
    - op: "replace" — update attribute(s)
    - op: "add" — same as replace for single-valued attrs
    - op: "remove" — set attribute to None/default

    Returns updated user dict or None on failure.
    """
    import users

    current = users.get_user(user_id)
    if not current:
        return None

    update_kwargs: Dict[str, Any] = {}

    for op_item in operations:
        op = op_item.get("op", "").lower()
        path = op_item.get("path", "")
        value = op_item.get("value")

        if op in ("replace", "add"):
            if not path and isinstance(value, dict):
                # No path: value is a dict of attributes to set
                mapped = scim_to_user_params(value)
                update_kwargs.update(mapped)
            elif path:
                _apply_single_attr(path, value, update_kwargs)
        elif op == "remove":
            if path:
                _apply_remove(path, update_kwargs)

    if not update_kwargs:
        return current

    return users.update_user(user_id, **update_kwargs)


def _apply_single_attr(path: str, value: Any, kwargs: Dict[str, Any]) -> None:
    """Map a single SCIM path + value to update kwargs."""
    path_lower = path.lower()

    if path_lower in ("username", "emails[type eq \"work\"].value", "emails.value"):
        kwargs["email"] = value
    elif path_lower == "displayname":
        kwargs["display_name"] = value
    elif path_lower == "active":
        kwargs["is_active"] = bool(value)
    elif path_lower == "name.formatted":
        kwargs["display_name"] = value
    elif path_lower == "name.givenname" or path_lower == "name.familyname":
        # Partial name update — best effort
        kwargs["display_name"] = str(value)
    elif path_lower.startswith(CUSTOM_SCHEMA_ROLE.lower()):
        # Extension attribute
        if "role" in path_lower:
            kwargs["role"] = value


def _apply_remove(path: str, kwargs: Dict[str, Any]) -> None:
    """Handle SCIM remove operation for a path."""
    path_lower = path.lower()
    if path_lower == "displayname" or path_lower == "name.formatted":
        kwargs["display_name"] = None
    # Don't allow removing email or active via SCIM remove


# ---------------------------------------------------------------------------
# SCIM list/query with pagination
# ---------------------------------------------------------------------------


def list_scim_users(
    filter_str: Optional[str] = None,
    start_index: int = 1,
    count: int = 100,
    base_url: str = "",
) -> Dict[str, Any]:
    """List users in SCIM ListResponse format.

    Args:
        filter_str: SCIM filter expression (optional).
        start_index: 1-indexed start position.
        count: Maximum results per page.
        base_url: Base URL for resource locations.

    Returns:
        SCIM ListResponse dict.
    """
    import users

    try:
        # Build query
        where_sql = ""
        params: list = []

        if filter_str:
            parsed = parse_scim_filter(filter_str)
            if parsed:
                where_sql, params = parsed

        conn = users._get_db_connection()
        cursor = conn.cursor()

        # Count total
        count_sql = "SELECT COUNT(*) FROM users"
        if where_sql:
            count_sql += f" WHERE {where_sql}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        # Fetch page (SCIM startIndex is 1-based)
        offset = max(0, start_index - 1)
        select_sql = "SELECT * FROM users"
        if where_sql:
            select_sql += f" WHERE {where_sql}"
        select_sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        cursor.execute(select_sql, params + [count, offset])

        rows = cursor.fetchall()
        user_list = [users._row_to_dict(row) for row in rows]

        return {
            "schemas": [SCIM_SCHEMA_LIST],
            "totalResults": total,
            "startIndex": start_index,
            "itemsPerPage": len(user_list),
            "Resources": [user_to_scim(u, base_url) for u in user_list],
        }
    except Exception as e:
        logger.error("Failed to list SCIM users: %s", e)
        return {
            "schemas": [SCIM_SCHEMA_LIST],
            "totalResults": 0,
            "startIndex": start_index,
            "itemsPerPage": 0,
            "Resources": [],
        }


# ---------------------------------------------------------------------------
# SCIM discovery endpoints (static responses)
# ---------------------------------------------------------------------------


def get_service_provider_config() -> Dict[str, Any]:
    """Return SCIM ServiceProviderConfig resource."""
    return {
        "schemas": [SCIM_SCHEMA_SP_CONFIG],
        "documentationUri": "https://pgvectorragindexer.com/docs/scim",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication scheme using the OAuth Bearer Token Standard",
                "specUri": "https://www.rfc-editor.org/info/rfc6750",
                "primary": True,
            }
        ],
    }


def get_resource_types() -> List[Dict[str, Any]]:
    """Return SCIM ResourceTypes."""
    return [
        {
            "schemas": [SCIM_SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/scim/v2/Users",
            "description": "User Account",
            "schema": SCIM_SCHEMA_USER,
            "schemaExtensions": [
                {
                    "schema": CUSTOM_SCHEMA_ROLE,
                    "required": False,
                }
            ],
        },
        {
            "schemas": [SCIM_SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/scim/v2/Groups",
            "description": "Group — maps to an internal role",
            "schema": SCIM_SCHEMA_GROUP,
            "schemaExtensions": [
                {
                    "schema": CUSTOM_SCHEMA_GROUP_ROLE,
                    "required": False,
                }
            ],
        },
    ]


def get_schemas() -> List[Dict[str, Any]]:
    """Return SCIM Schemas for User and Group resources."""
    schemas = [
        {
            "schemas": [SCIM_SCHEMA_SCHEMA],
            "id": SCIM_SCHEMA_USER,
            "name": "User",
            "description": "User Account",
            "attributes": [
                {
                    "name": "userName",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "server",
                },
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
                {
                    "name": "emails",
                    "type": "complex",
                    "multiValued": True,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "subAttributes": [
                        {"name": "value", "type": "string", "mutability": "readWrite"},
                        {"name": "type", "type": "string", "mutability": "readWrite"},
                        {"name": "primary", "type": "boolean", "mutability": "readWrite"},
                    ],
                },
                {
                    "name": "active",
                    "type": "boolean",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
            ],
        },
        {
            "schemas": [SCIM_SCHEMA_SCHEMA],
            "id": CUSTOM_SCHEMA_ROLE,
            "name": "PGVectorRAGIndexer User Extension",
            "description": "Custom role extension for PGVectorRAGIndexer",
            "attributes": [
                {
                    "name": "role",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "caseExact": True,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                    "description": "User role: 'admin' or 'user'",
                },
            ],
        },
    ]

    # Group schema
    schemas.append({
        "schemas": [SCIM_SCHEMA_SCHEMA],
        "id": SCIM_SCHEMA_GROUP,
        "name": "Group",
        "description": "Group resource for role-based access mapping",
        "attributes": [
            {
                "name": "displayName",
                "type": "string",
                "multiValued": False,
                "required": True,
                "caseExact": False,
                "mutability": "readWrite",
                "returned": "default",
                "uniqueness": "server",
            },
            {
                "name": "members",
                "type": "complex",
                "multiValued": True,
                "required": False,
                "mutability": "readWrite",
                "returned": "default",
                "subAttributes": [
                    {"name": "value", "type": "string", "mutability": "readWrite",
                     "description": "User id"},
                    {"name": "display", "type": "string", "mutability": "readOnly"},
                    {"name": "$ref", "type": "reference", "mutability": "readOnly"},
                ],
            },
        ],
    })

    # Group role extension schema
    schemas.append({
        "schemas": [SCIM_SCHEMA_SCHEMA],
        "id": CUSTOM_SCHEMA_GROUP_ROLE,
        "name": "PGVectorRAGIndexer Group Extension",
        "description": "Maps a SCIM group to an internal role",
        "attributes": [
            {
                "name": "roleName",
                "type": "string",
                "multiValued": False,
                "required": False,
                "caseExact": True,
                "mutability": "readWrite",
                "returned": "default",
                "uniqueness": "none",
                "description": "Internal role name this group maps to",
            },
        ],
    })

    return schemas


# ---------------------------------------------------------------------------
# SCIM Group ↔ internal role mapping
# ---------------------------------------------------------------------------


def _get_db_connection():
    """Get a pooled database connection as a context manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


def _group_row_to_dict(row) -> Dict[str, Any]:
    """Convert a scim_groups row to a dict."""
    cols = ("id", "external_id", "display_name", "role_name", "created_at", "updated_at")
    d = dict(zip(cols, row))
    for ts_key in ("created_at", "updated_at"):
        val = d.get(ts_key)
        if isinstance(val, datetime):
            d[ts_key] = val.isoformat()
    return d


def get_group_members(role_name: str, base_url: str = "") -> List[Dict[str, Any]]:
    """Return SCIM member references for all active users with the given role."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, display_name FROM users WHERE role = %s AND is_active = true",
            (role_name,),
        )
        members = []
        for row in cursor.fetchall():
            member: Dict[str, Any] = {
                "value": row[0],
                "display": row[2] or row[1] or "",
            }
            if base_url:
                member["$ref"] = f"{base_url}/scim/v2/Users/{row[0]}"
            members.append(member)
        return members


def group_to_scim(group: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    """Convert an internal group dict to a SCIM 2.0 Group resource."""
    members = get_group_members(group["role_name"], base_url)
    scim_group: Dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_GROUP, CUSTOM_SCHEMA_GROUP_ROLE],
        "id": group["id"],
        "displayName": group["display_name"],
        "members": members,
        "meta": {
            "resourceType": "Group",
            "created": group.get("created_at", ""),
            "lastModified": group.get("updated_at", ""),
        },
        CUSTOM_SCHEMA_GROUP_ROLE: {
            "roleName": group["role_name"],
        },
    }
    if group.get("external_id"):
        scim_group["externalId"] = group["external_id"]
    if base_url:
        scim_group["meta"]["location"] = f"{base_url}/scim/v2/Groups/{group['id']}"
    return scim_group


def _resolve_role_name(scim_data: Dict[str, Any]) -> str:
    """Determine the internal role name from a SCIM Group resource.

    Priority:
    1. Custom extension roleName if present
    2. Case-insensitive match of displayName against existing roles
    3. Fall back to SCIM_DEFAULT_ROLE
    """
    ext = scim_data.get(CUSTOM_SCHEMA_GROUP_ROLE, {})
    if "roleName" in ext:
        return ext["roleName"]

    display = scim_data.get("displayName", "")
    if display:
        from role_permissions import is_valid_role
        # Try exact, then lowercase
        if is_valid_role(display):
            return display
        if is_valid_role(display.lower()):
            return display.lower()

    return SCIM_DEFAULT_ROLE


def create_scim_group(
    display_name: str, role_name: str, external_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a SCIM group mapping to an internal role."""
    from role_permissions import is_valid_role
    if not is_valid_role(role_name):
        raise ValueError(f"Role '{role_name}' does not exist")

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO scim_groups (display_name, role_name, external_id)
            VALUES (%s, %s, %s)
            RETURNING id, external_id, display_name, role_name, created_at, updated_at
            """,
            (display_name, role_name, external_id),
        )
        row = cursor.fetchone()
        conn.commit()
    return _group_row_to_dict(row)


def get_scim_group(group_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a SCIM group by id."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, external_id, display_name, role_name, created_at, updated_at "
            "FROM scim_groups WHERE id = %s",
            (group_id,),
        )
        row = cursor.fetchone()
    return _group_row_to_dict(row) if row else None


def update_scim_group(
    group_id: str,
    display_name: Optional[str] = None,
    role_name: Optional[str] = None,
    external_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a SCIM group's mapping."""
    if role_name:
        from role_permissions import is_valid_role
        if not is_valid_role(role_name):
            raise ValueError(f"Role '{role_name}' does not exist")

    sets = []
    params: list = []
    if display_name is not None:
        sets.append("display_name = %s")
        params.append(display_name)
    if role_name is not None:
        sets.append("role_name = %s")
        params.append(role_name)
    if external_id is not None:
        sets.append("external_id = %s")
        params.append(external_id)
    if not sets:
        return get_scim_group(group_id)

    sets.append("updated_at = now()")
    params.append(group_id)

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE scim_groups SET {', '.join(sets)} WHERE id = %s "
            "RETURNING id, external_id, display_name, role_name, created_at, updated_at",
            params,
        )
        row = cursor.fetchone()
        conn.commit()
    return _group_row_to_dict(row) if row else None


def delete_scim_group(group_id: str) -> bool:
    """Delete a SCIM group mapping. Does not affect users or the underlying role."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scim_groups WHERE id = %s", (group_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
    return deleted


def list_scim_groups(
    filter_str: Optional[str] = None,
    start_index: int = 1,
    count: int = 100,
    base_url: str = "",
) -> Dict[str, Any]:
    """List SCIM groups with optional filtering and pagination."""
    group_attr_map = {
        "displayName": "display_name",
        "displayname": "display_name",
        "externalId": "external_id",
        "externalid": "external_id",
        "id": "id",
    }

    where_sql = ""
    params: list = []

    if filter_str:
        parsed = parse_scim_filter(filter_str, attr_map=group_attr_map)
        if parsed:
            where_sql, params = parsed

    with _get_db_connection() as conn:
        cursor = conn.cursor()
        count_sql = "SELECT COUNT(*) FROM scim_groups"
        if where_sql:
            count_sql += f" WHERE {where_sql}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = max(0, start_index - 1)
        select_sql = (
            "SELECT id, external_id, display_name, role_name, created_at, updated_at "
            "FROM scim_groups"
        )
        if where_sql:
            select_sql += f" WHERE {where_sql}"
        select_sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        cursor.execute(select_sql, params + [count, offset])
        rows = cursor.fetchall()

    groups = [_group_row_to_dict(r) for r in rows]
    return {
        "schemas": [SCIM_SCHEMA_LIST],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(groups),
        "Resources": [group_to_scim(g, base_url) for g in groups],
    }


def apply_group_membership(group_id: str, operations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Apply SCIM PATCH operations to a group (membership changes + attribute updates).

    Membership operations:
    - add members: set each user's role to the group's role
    - remove members: revert each user to SCIM_DEFAULT_ROLE
    - replace displayName or extension roleName: update group mapping
    """
    import users as users_mod

    group = get_scim_group(group_id)
    if not group:
        return None

    update_kwargs: Dict[str, Any] = {}

    for op_item in operations:
        op = op_item.get("op", "").lower()
        path = (op_item.get("path") or "").lower()
        value = op_item.get("value")

        if op in ("add", "replace") and path == "members":
            # Add/replace members: set their role to this group's role
            member_list = value if isinstance(value, list) else [value]
            for member in member_list:
                uid = member.get("value") if isinstance(member, dict) else member
                if uid:
                    users_mod.change_role(uid, group["role_name"])
                    logger.info("SCIM group %s: set user %s role to %s", group_id, uid, group["role_name"])

        elif op == "remove" and path == "members":
            # Remove members: revert to default role
            member_list = value if isinstance(value, list) else ([value] if value else [])
            for member in member_list:
                uid = member.get("value") if isinstance(member, dict) else member
                if uid:
                    users_mod.change_role(uid, SCIM_DEFAULT_ROLE)
                    logger.info("SCIM group %s: reverted user %s to %s", group_id, uid, SCIM_DEFAULT_ROLE)

        elif op in ("add", "replace"):
            # Attribute updates
            if path == "displayname" or (not path and isinstance(value, dict) and "displayName" in value):
                dn = value if isinstance(value, str) else value.get("displayName", "")
                if dn:
                    update_kwargs["display_name"] = dn
            elif path.startswith(CUSTOM_SCHEMA_GROUP_ROLE.lower()):
                if "rolename" in path and isinstance(value, str):
                    update_kwargs["role_name"] = value

    if update_kwargs:
        group = update_scim_group(group_id, **update_kwargs)

    return group
