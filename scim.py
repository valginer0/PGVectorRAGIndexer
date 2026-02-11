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


def parse_scim_filter(filter_str: str) -> Optional[Tuple[str, list]]:
    """Parse a SCIM filter string into a SQL WHERE clause and params.

    Supports a practical subset of SCIM filtering:
    - Simple comparisons: attr eq "value", attr co "value", attr sw "value"
    - Boolean: and, or
    - Nested attributes: emails.value, name.givenName

    Returns (sql_fragment, params) or None if unparseable.
    """
    if not filter_str or not filter_str.strip():
        return None

    # Attribute → column mapping
    attr_map = {
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
        }
    ]


def get_schemas() -> List[Dict[str, Any]]:
    """Return SCIM Schemas for the User resource."""
    return [
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
