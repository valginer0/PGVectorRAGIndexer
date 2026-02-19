"""
Virtual Roots module (#9).

CRUD operations for virtual roots (named path mappings per client).
Enables cross-platform path resolution in remote/multi-user setups.

Example:
    "FinanceDocs" → "C:\\Finance" (client A, Windows)
    "FinanceDocs" → "/mnt/finance" (client B, Linux)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection_raw()


_COLUMNS = ("id", "name", "client_id", "local_path", "created_at", "updated_at")


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def add_root(
    name: str,
    client_id: str,
    local_path: str,
) -> Optional[Dict[str, Any]]:
    """Add or update a virtual root mapping.

    Uses upsert: if (name, client_id) already exists, updates local_path.
    Returns the created/updated row as a dict, or None on failure.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO virtual_roots (name, client_id, local_path)
            VALUES (%s, %s, %s)
            ON CONFLICT (name, client_id) DO UPDATE SET
                local_path = EXCLUDED.local_path,
                updated_at = now()
            RETURNING {cols}
            """.format(cols=", ".join(_COLUMNS)),
            (name, client_id, local_path),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to add virtual root %s: %s", name, e)
        return None


def remove_root(root_id: str) -> bool:
    """Remove a virtual root by ID. Returns True on success."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM virtual_roots WHERE id = %s", (root_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning("Failed to remove virtual root %s: %s", root_id, e)
        return False


def remove_root_by_name(name: str, client_id: str) -> bool:
    """Remove a virtual root by (name, client_id). Returns True on success."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM virtual_roots WHERE name = %s AND client_id = %s",
            (name, client_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning("Failed to remove virtual root %s/%s: %s", name, client_id, e)
        return False


def get_root(root_id: str) -> Optional[Dict[str, Any]]:
    """Get a single virtual root by ID."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT {cols} FROM virtual_roots WHERE id = %s".format(
                cols=", ".join(_COLUMNS)
            ),
            (root_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get virtual root %s: %s", root_id, e)
        return None


def list_roots(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List virtual roots, optionally filtered by client_id."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        sql = "SELECT {cols} FROM virtual_roots".format(cols=", ".join(_COLUMNS))
        params = []
        if client_id:
            sql += " WHERE client_id = %s"
            params.append(client_id)
        sql += " ORDER BY name, client_id"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list virtual roots: %s", e)
        return []


def list_root_names() -> List[str]:
    """List distinct virtual root names (across all clients)."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT name FROM virtual_roots ORDER BY name")
        names = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return names
    except Exception as e:
        logger.warning("Failed to list virtual root names: %s", e)
        return []


def get_mappings_for_root(name: str) -> List[Dict[str, Any]]:
    """Get all client mappings for a given virtual root name.

    Returns a list of dicts with client_id, local_path, etc.
    Useful for the details panel showing all client mappings.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT vr.{cols}, c.display_name, c.os_type
            FROM virtual_roots vr
            LEFT JOIN clients c ON c.id = vr.client_id
            WHERE vr.name = %s
            ORDER BY c.display_name
            """.format(cols=", vr.".join(_COLUMNS)),
            (name,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for row in rows:
            d = _row_to_dict(row[:len(_COLUMNS)])
            d["client_display_name"] = row[len(_COLUMNS)]
            d["client_os_type"] = row[len(_COLUMNS) + 1]
            result.append(d)
        return result
    except Exception as e:
        logger.warning("Failed to get mappings for root %s: %s", name, e)
        return []


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_path(virtual_path: str, client_id: str) -> Optional[str]:
    """Resolve a virtual path like 'FinanceDocs/reports/q1.pdf' to a local path.

    Splits on the first '/' to get the root name, looks up the local_path
    for the given client, and joins the remainder.

    Returns the resolved local path, or None if the root is not mapped.
    """
    import os

    parts = virtual_path.split("/", 1)
    root_name = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""

    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT local_path FROM virtual_roots WHERE name = %s AND client_id = %s",
            (root_name, client_id),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return os.path.join(row[0], remainder) if remainder else row[0]
        return None
    except Exception as e:
        logger.warning("Failed to resolve path %s for client %s: %s",
                       virtual_path, client_id, e)
        return None
