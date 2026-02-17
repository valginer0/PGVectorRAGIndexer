"""
Role-based permissions for #16 Enterprise Foundations Phase 4a.

Simple named-roles approach: roles are strings stored in users.role,
permissions are mapped via a JSON config file (role_permissions.json).

Upgrade path to Phase 4b (DB-backed RBAC):
- Replace load_role_config() to read from a `roles` table instead of JSON
- The rest of the API (has_permission, get_role_permissions, etc.) stays the same

Granular permissions:
    documents.read      — search and retrieve documents
    documents.write     — index/upload documents
    documents.delete    — delete documents
    documents.visibility — manage own document visibility
    documents.visibility.all — manage any document's visibility (admin)
    health.view         — view indexing health dashboard
    audit.view          — view audit/activity log
    users.manage        — create/update/delete users, change roles
    keys.manage         — create/revoke/rotate API keys
    system.admin        — full system access (SCIM config, SAML, etc.)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

# Document permissions
PERM_DOCUMENTS_READ = "documents.read"
PERM_DOCUMENTS_WRITE = "documents.write"
PERM_DOCUMENTS_DELETE = "documents.delete"
PERM_DOCUMENTS_VISIBILITY = "documents.visibility"
PERM_DOCUMENTS_VISIBILITY_ALL = "documents.visibility.all"

# Operational permissions
PERM_HEALTH_VIEW = "health.view"
PERM_AUDIT_VIEW = "audit.view"

# Management permissions
PERM_USERS_MANAGE = "users.manage"
PERM_KEYS_MANAGE = "keys.manage"

# System permissions
PERM_SYSTEM_ADMIN = "system.admin"

ALL_PERMISSIONS: FrozenSet[str] = frozenset({
    PERM_DOCUMENTS_READ,
    PERM_DOCUMENTS_WRITE,
    PERM_DOCUMENTS_DELETE,
    PERM_DOCUMENTS_VISIBILITY,
    PERM_DOCUMENTS_VISIBILITY_ALL,
    PERM_HEALTH_VIEW,
    PERM_AUDIT_VIEW,
    PERM_USERS_MANAGE,
    PERM_KEYS_MANAGE,
    PERM_SYSTEM_ADMIN,
})

# ---------------------------------------------------------------------------
# Built-in role definitions (defaults if no config file exists)
# ---------------------------------------------------------------------------

BUILTIN_ROLES: Dict[str, Dict[str, Any]] = {
    "admin": {
        "description": "Full system access",
        "permissions": sorted(ALL_PERMISSIONS),
        "is_system": True,
    },
    "user": {
        "description": "Standard user — index and search documents",
        "permissions": [
            PERM_DOCUMENTS_READ,
            PERM_DOCUMENTS_WRITE,
            PERM_DOCUMENTS_VISIBILITY,
        ],
        "is_system": True,
    },
    "researcher": {
        "description": "Read-heavy role — search and index, manage own visibility",
        "permissions": [
            PERM_DOCUMENTS_READ,
            PERM_DOCUMENTS_WRITE,
            PERM_DOCUMENTS_VISIBILITY,
        ],
        "is_system": False,
    },
    "sre": {
        "description": "Operations role — full document access, health monitoring, audit",
        "permissions": [
            PERM_DOCUMENTS_READ,
            PERM_DOCUMENTS_WRITE,
            PERM_DOCUMENTS_DELETE,
            PERM_DOCUMENTS_VISIBILITY,
            PERM_DOCUMENTS_VISIBILITY_ALL,
            PERM_HEALTH_VIEW,
            PERM_AUDIT_VIEW,
        ],
        "is_system": False,
    },
    "support": {
        "description": "Support role — read-only access with health and audit visibility",
        "permissions": [
            PERM_DOCUMENTS_READ,
            PERM_HEALTH_VIEW,
            PERM_AUDIT_VIEW,
        ],
        "is_system": False,
    },
}

# ---------------------------------------------------------------------------
# Config loading — Phase 4b: DB-backed with JSON/built-in fallback
# ---------------------------------------------------------------------------

_CONFIG_FILE = os.environ.get(
    "ROLE_PERMISSIONS_CONFIG",
    str(Path(__file__).parent / "role_permissions.json"),
)

# Cached config (loaded once, reloadable)
_role_config: Optional[Dict[str, Dict[str, Any]]] = None


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


def _load_from_db() -> Optional[Dict[str, Dict[str, Any]]]:
    """Attempt to load roles from the DB `roles` table.

    Returns None if the DB is unavailable or the table doesn't exist.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT name, description, permissions, is_system FROM roles ORDER BY name"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return None

        config: Dict[str, Dict[str, Any]] = {}
        for name, description, permissions, is_system in rows:
            # permissions may be a list (from JSONB) or a string
            perms = permissions if isinstance(permissions, list) else []
            config[name] = {
                "description": description or "",
                "permissions": perms,
                "is_system": bool(is_system),
            }

        # Ensure admin always has all permissions (safety guard)
        if "admin" in config:
            config["admin"]["permissions"] = sorted(ALL_PERMISSIONS)
            config["admin"]["is_system"] = True

        return config
    except Exception as e:
        logger.debug("Could not load roles from DB: %s — will use fallback", e)
        return None


def load_role_config(force_reload: bool = False) -> Dict[str, Dict[str, Any]]:
    """Load role → permissions mapping.

    Priority order:
    1. DB `roles` table (Phase 4b)
    2. role_permissions.json config file
    3. Built-in BUILTIN_ROLES defaults

    The config is cached after first load; use force_reload=True to re-read.
    """
    global _role_config
    if _role_config is not None and not force_reload:
        return _role_config

    # Try DB first (Phase 4b)
    db_config = _load_from_db()
    if db_config:
        _role_config = db_config
        logger.info("Loaded role permissions from DB (%d roles)", len(db_config))
        return _role_config

    # Fallback to JSON config file
    config_path = Path(_CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                loaded = json.load(f)
            # Validate structure
            if isinstance(loaded, dict):
                # Ensure admin always has all permissions
                if "admin" in loaded:
                    loaded["admin"]["permissions"] = sorted(ALL_PERMISSIONS)
                    loaded["admin"]["is_system"] = True
                _role_config = loaded
                logger.info("Loaded role permissions from %s (%d roles)", config_path, len(loaded))
                return _role_config
        except Exception as e:
            logger.error("Failed to load role_permissions.json: %s — using defaults", e)

    _role_config = dict(BUILTIN_ROLES)
    return _role_config


def save_role_config(config: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
    """Save the current role config to the JSON file (legacy fallback).

    Returns True on success.
    """
    global _role_config
    if config is not None:
        _role_config = config

    if _role_config is None:
        return False

    try:
        config_path = Path(_CONFIG_FILE)
        with open(config_path, "w") as f:
            json.dump(_role_config, f, indent=2, sort_keys=True)
        logger.info("Saved role permissions to %s", config_path)
        return True
    except Exception as e:
        logger.error("Failed to save role_permissions.json: %s", e)
        return False


# ---------------------------------------------------------------------------
# DB CRUD for roles (Phase 4b)
# ---------------------------------------------------------------------------


def create_role(
    name: str,
    description: str = "",
    permissions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new custom role in the DB.

    Args:
        name: Role name (must be unique).
        description: Human-readable description.
        permissions: List of permission strings.

    Returns:
        Dict with the created role info.

    Raises:
        ValueError: If the role name already exists or is invalid.
    """
    if not name or not name.strip():
        raise ValueError("Role name cannot be empty")

    perms = permissions or []
    # Validate permissions
    invalid = set(perms) - ALL_PERMISSIONS
    if invalid:
        raise ValueError(f"Invalid permissions: {', '.join(sorted(invalid))}")

    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO roles (name, description, permissions, is_system)
            VALUES (%s, %s, %s::jsonb, FALSE)
            RETURNING name, description, permissions, is_system, created_at
            """,
            (name.strip(), description, json.dumps(sorted(perms))),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        # Invalidate cache
        global _role_config
        _role_config = None

        return {
            "name": row[0],
            "description": row[1],
            "permissions": row[2] if isinstance(row[2], list) else [],
            "is_system": bool(row[3]),
            "created_at": row[4].isoformat() if row[4] else None,
        }
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            raise ValueError(f"Role '{name}' already exists")
        raise


def update_role(
    name: str,
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Update an existing role's description and/or permissions.

    System roles (admin, user) cannot have their is_system flag changed.
    Admin role permissions are always enforced to ALL_PERMISSIONS.

    Returns:
        Updated role dict, or None if role not found.

    Raises:
        ValueError: If trying to update a system role's protected attributes.
    """
    if name == "admin" and permissions is not None:
        # Admin always gets all permissions — silently override
        permissions = sorted(ALL_PERMISSIONS)

    # Validate permissions if provided
    if permissions is not None:
        invalid = set(permissions) - ALL_PERMISSIONS
        if invalid:
            raise ValueError(f"Invalid permissions: {', '.join(sorted(invalid))}")

    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        sets = []
        params: list = []
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if permissions is not None:
            sets.append("permissions = %s::jsonb")
            params.append(json.dumps(sorted(permissions)))

        if not sets:
            return get_role_info(name)

        sets.append("updated_at = now()")
        params.append(name)

        cur.execute(
            f"UPDATE roles SET {', '.join(sets)} WHERE name = %s "
            "RETURNING name, description, permissions, is_system, updated_at",
            params,
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not row:
            return None

        # Invalidate cache
        global _role_config
        _role_config = None

        return {
            "name": row[0],
            "description": row[1],
            "permissions": row[2] if isinstance(row[2], list) else [],
            "is_system": bool(row[3]),
            "updated_at": row[4].isoformat() if row[4] else None,
        }
    except Exception as e:
        logger.error("Failed to update role '%s': %s", name, e)
        raise


def delete_role(name: str) -> bool:
    """Delete a custom role from the DB.

    System roles (is_system=True) cannot be deleted.

    Returns:
        True if the role was deleted.

    Raises:
        ValueError: If trying to delete a system role.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Check if system role
        cur.execute("SELECT is_system FROM roles WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return False
        if row[0]:
            cur.close()
            conn.close()
            raise ValueError(f"Cannot delete system role '{name}'")

        cur.execute("DELETE FROM roles WHERE name = %s AND is_system = FALSE", (name,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()

        if deleted:
            # Invalidate cache
            global _role_config
            _role_config = None

        return deleted
    except ValueError:
        raise
    except Exception as e:
        logger.error("Failed to delete role '%s': %s", name, e)
        raise


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------


def get_valid_roles() -> Set[str]:
    """Return the set of all valid role names (from config)."""
    config = load_role_config()
    return set(config.keys())


def get_role_permissions(role: str) -> List[str]:
    """Get the permissions list for a role.

    Returns empty list if role is unknown.
    """
    config = load_role_config()
    role_def = config.get(role, {})
    return list(role_def.get("permissions", []))


def get_role_info(role: str) -> Optional[Dict[str, Any]]:
    """Get full role definition (description, permissions, is_system).

    Returns None if role is unknown.
    """
    config = load_role_config()
    role_def = config.get(role)
    if role_def is None:
        return None
    return {
        "name": role,
        "description": role_def.get("description", ""),
        "permissions": list(role_def.get("permissions", [])),
        "is_system": role_def.get("is_system", False),
    }


def list_roles() -> List[Dict[str, Any]]:
    """List all roles with their definitions."""
    config = load_role_config()
    return [
        {
            "name": name,
            "description": defn.get("description", ""),
            "permissions": list(defn.get("permissions", [])),
            "is_system": defn.get("is_system", False),
        }
        for name, defn in sorted(config.items())
    ]


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission.

    Admin role always has all permissions.
    The system.admin permission grants all other permissions.
    """
    perms = get_role_permissions(role)

    # system.admin grants everything
    if PERM_SYSTEM_ADMIN in perms:
        return True

    return permission in perms


def is_valid_role(role: str) -> bool:
    """Check if a role name is defined in the config."""
    return role in get_valid_roles()


def list_permissions() -> List[Dict[str, str]]:
    """List all available permissions with descriptions."""
    descriptions = {
        PERM_DOCUMENTS_READ: "Search and retrieve documents",
        PERM_DOCUMENTS_WRITE: "Index and upload documents",
        PERM_DOCUMENTS_DELETE: "Delete documents",
        PERM_DOCUMENTS_VISIBILITY: "Manage own document visibility",
        PERM_DOCUMENTS_VISIBILITY_ALL: "Manage any document's visibility",
        PERM_HEALTH_VIEW: "View indexing health dashboard",
        PERM_AUDIT_VIEW: "View audit and activity log",
        PERM_USERS_MANAGE: "Create, update, delete users and change roles",
        PERM_KEYS_MANAGE: "Create, revoke, and rotate API keys",
        PERM_SYSTEM_ADMIN: "Full system access (SCIM, SAML, config)",
    }
    return [
        {"permission": p, "description": descriptions.get(p, "")}
        for p in sorted(ALL_PERMISSIONS)
    ]
