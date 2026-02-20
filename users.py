"""
Users module for RBAC and enterprise auth (#16).

Manages user accounts with role-based access control.
Built-in roles: 'admin' (full access) and 'user' (index + search).
Custom roles (e.g. 'researcher', 'sre', 'support') are defined in
role_permissions.json — see role_permissions.py for details.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Built-in role constants (kept for backward compat)
ROLE_ADMIN = "admin"
ROLE_USER = "user"


def _get_valid_roles():
    """Get valid roles from role_permissions config (dynamic)."""
    try:
        from role_permissions import get_valid_roles
        return get_valid_roles()
    except Exception:
        # Fallback if role_permissions not available
        return {ROLE_ADMIN, ROLE_USER}


# Legacy constant — now delegates to config. Code that checks
# `role in VALID_ROLES` should use `_get_valid_roles()` instead.
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}

# Valid auth providers
AUTH_PROVIDER_API_KEY = "api_key"
AUTH_PROVIDER_SAML = "saml"
VALID_AUTH_PROVIDERS = {AUTH_PROVIDER_API_KEY, AUTH_PROVIDER_SAML}

_COLUMNS = (
    "id", "email", "display_name", "role", "auth_provider",
    "api_key_id", "client_id", "created_at", "updated_at",
    "last_login_at", "is_active",
)


def _get_db_connection():
    """Get a pooled database connection as a context manager.

    Always use with ``with _get_db_connection() as conn:`` to ensure
    the connection is returned to the pool after use.
    """
    from database import get_db_manager
    return get_db_manager().get_connection()


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    for ts_key in ("created_at", "updated_at", "last_login_at"):
        val = d.get(ts_key)
        if isinstance(val, datetime):
            d[ts_key] = val.isoformat()
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_user(
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    role: str = ROLE_USER,
    auth_provider: str = AUTH_PROVIDER_API_KEY,
    api_key_id: Optional[int] = None,
    client_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Create a new user.

    Returns the created user dict, or None on failure.
    """
    if role not in _get_valid_roles():
        logger.error("Invalid role: %s", role)
        return None
    if auth_provider not in VALID_AUTH_PROVIDERS:
        logger.error("Invalid auth_provider: %s", auth_provider)
        return None

    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (email, display_name, role, auth_provider, api_key_id, client_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, email, display_name, role, auth_provider,
                          api_key_id, client_id, created_at, updated_at,
                          last_login_at, is_active
                """,
                (email, display_name, role, auth_provider, api_key_id, client_id),
            )
            row = cursor.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error("Failed to create user: %s", e)
        return None


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Get a user by ID."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error("Failed to get user %s: %s", user_id, e)
        return None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get a user by email address."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error("Failed to get user by email %s: %s", email, e)
        return None


def get_user_by_api_key(api_key_id: int) -> Optional[Dict[str, Any]]:
    """Get a user linked to a specific API key."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE api_key_id = %s AND is_active = true",
                (api_key_id,),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error("Failed to get user by api_key_id %s: %s", api_key_id, e)
        return None


def list_users(
    *,
    role: Optional[str] = None,
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """List users, optionally filtered by role and active status."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params: list = []
            if role:
                conditions.append("role = %s")
                params.append(role)
            if active_only:
                conditions.append("is_active = true")
            where = " AND ".join(conditions)
            sql = "SELECT * FROM users"
            if where:
                sql += f" WHERE {where}"
            sql += " ORDER BY created_at DESC"
            cursor.execute(sql, params)
            return [_row_to_dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        return []


def update_user(
    user_id: str,
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Update a user's fields. Only non-None values are updated."""
    sets = []
    params: list = []
    if email is not None:
        sets.append("email = %s")
        params.append(email)
    if display_name is not None:
        sets.append("display_name = %s")
        params.append(display_name)
    if role is not None:
        if role not in _get_valid_roles():
            logger.error("Invalid role: %s", role)
            return None
        sets.append("role = %s")
        params.append(role)
    if is_active is not None:
        sets.append("is_active = %s")
        params.append(is_active)

    if not sets:
        return get_user(user_id)

    sets.append("updated_at = now()")
    params.append(user_id)

    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE id = %s "
                "RETURNING id, email, display_name, role, auth_provider, "
                "api_key_id, client_id, created_at, updated_at, last_login_at, is_active",
                params,
            )
            row = cursor.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error("Failed to update user %s: %s", user_id, e)
        return None


def delete_user(user_id: str) -> bool:
    """Delete a user (hard delete)."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("Failed to delete user %s: %s", user_id, e)
        return False


def deactivate_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Soft-deactivate a user (set is_active = false)."""
    return update_user(user_id, is_active=False)


# ---------------------------------------------------------------------------
# Role checks
# ---------------------------------------------------------------------------


def is_admin(user_id: str) -> bool:
    """Check if a user has the admin role."""
    user = get_user(user_id)
    return user is not None and user.get("role") == ROLE_ADMIN


def record_login(user_id: str) -> None:
    """Update last_login_at for a user."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login_at = now(), updated_at = now() WHERE id = %s",
                (user_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to record login for user %s: %s", user_id, e)


def change_role(user_id: str, new_role: str) -> Optional[Dict[str, Any]]:
    """Change a user's role. Returns updated user or None."""
    return update_user(user_id, role=new_role)


def count_admins() -> int:
    """Count the number of active admin users."""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE role = %s AND is_active = true",
                (ROLE_ADMIN,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error("Failed to count admins: %s", e)
        return 0
