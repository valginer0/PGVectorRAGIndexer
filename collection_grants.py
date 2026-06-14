"""
Role-based collection grants for document-set access control (Phase 4b slice).

A "collection" is the existing document ``namespace`` dimension (metadata key
in PostgreSQL, real column in the LanceDB tables). Grants give a role read
access to collections; enforcement happens at search time in
routers/search_api.py via the ``allowed_namespaces`` filter.

Semantics:
- A role with NO grant rows is unrestricted (backward compatible: grants are
  opt-in per role).
- A role with grant rows sees only documents whose namespace is granted.
- The wildcard namespace '*' makes the role unrestricted while keeping the
  role listed in the grants table.
- Admins (system.admin permission) are never restricted.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WILDCARD_NAMESPACE = "*"


def _get_db_connection():
    from database import get_db_manager
    return get_db_manager().get_connection()


def list_grants(role: Optional[str] = None) -> List[Dict[str, Any]]:
    """List collection grants, optionally for a single role."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        if role:
            cursor.execute(
                "SELECT role, namespace, created_at FROM role_collection_grants "
                "WHERE role = %s ORDER BY namespace",
                (role,),
            )
        else:
            cursor.execute(
                "SELECT role, namespace, created_at FROM role_collection_grants "
                "ORDER BY role, namespace"
            )
        return [
            {"role": row[0], "namespace": row[1], "created_at": row[2]}
            for row in cursor.fetchall()
        ]


def grant_collection(role: str, namespace: str) -> bool:
    """Grant a role read access to a collection. Returns False if the role is unknown."""
    from role_permissions import get_valid_roles

    if role not in get_valid_roles():
        logger.error("Cannot grant collection to unknown role: %s", role)
        return False
    if not namespace or not namespace.strip():
        raise ValueError("namespace must be non-empty")
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO role_collection_grants (role, namespace) VALUES (%s, %s) "
            "ON CONFLICT (role, namespace) DO NOTHING",
            (role, namespace.strip()),
        )
        conn.commit()
    return True


def revoke_collection(role: str, namespace: str) -> int:
    """Revoke a grant. Returns the number of rows removed (0 or 1)."""
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM role_collection_grants WHERE role = %s AND namespace = %s",
            (role, namespace),
        )
        deleted = cursor.rowcount
        conn.commit()
    return deleted


def allowed_namespaces_for_role(role: Optional[str]) -> Optional[List[str]]:
    """Return the namespaces a role may read, or None for unrestricted.

    None (unrestricted) when: no role context, the role has no grant rows,
    or the role holds the '*' wildcard grant.
    """
    if not role:
        return None
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT namespace FROM role_collection_grants WHERE role = %s",
            (role,),
        )
        namespaces = [row[0] for row in cursor.fetchall()]
    if not namespaces or WILDCARD_NAMESPACE in namespaces:
        return None
    return namespaces


def search_allowed_namespaces_for_key_record(
    key_record: Optional[Dict[str, Any]],
) -> Optional[List[str]]:
    """Resolve an API key record to the namespaces its user may search.

    None = unrestricted. Mirrors the identity rules of
    document_visibility.search_exclusions_for_key_record: local/no-auth mode
    and admins are unrestricted; an API key not linked to a user gets no
    role and is therefore unrestricted by grants (visibility rules still
    hide all private docs from it).
    """
    if not isinstance(key_record, dict):
        return None
    from users import get_user_by_api_key
    from role_permissions import has_permission

    user = get_user_by_api_key(key_record["id"])
    if user is None:
        return None
    role = user.get("role", "")
    if has_permission(role, "system.admin"):
        return None
    return allowed_namespaces_for_role(role)
