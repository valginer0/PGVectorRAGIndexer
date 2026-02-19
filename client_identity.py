"""
Client Identity module (#8).

Manages client registration, heartbeat, and lookup.
Each desktop app instance gets a unique client_id on first run,
stored locally and registered with the server.
"""

import logging
import platform
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from db import get_db_manager
    return get_db_manager().get_connection_raw()


# ---------------------------------------------------------------------------
# Client registration & heartbeat (server-side)
# ---------------------------------------------------------------------------


def register_client(
    client_id: str,
    display_name: str,
    os_type: str,
    app_version: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Register or update a client in the database.

    Uses INSERT ... ON CONFLICT to upsert: if the client_id already exists,
    update display_name, os_type, app_version, and last_seen_at.

    Returns the client row as a dict, or None on failure.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clients (id, display_name, os_type, app_version, last_seen_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                os_type = EXCLUDED.os_type,
                app_version = EXCLUDED.app_version,
                last_seen_at = now()
            RETURNING id, display_name, os_type, app_version,
                      last_seen_at, created_at
            """,
            (client_id, display_name, os_type, app_version),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if row:
            return _row_to_dict(row)
        return None
    except Exception as e:
        logger.warning("Failed to register client %s: %s", client_id, e)
        return None


def heartbeat(client_id: str, app_version: Optional[str] = None) -> bool:
    """Update last_seen_at for an existing client.

    Returns True on success, False on failure.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        if app_version:
            cur.execute(
                "UPDATE clients SET last_seen_at = now(), app_version = %s WHERE id = %s",
                (app_version, client_id),
            )
        else:
            cur.execute(
                "UPDATE clients SET last_seen_at = now() WHERE id = %s",
                (client_id,),
            )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.warning("Failed to heartbeat client %s: %s", client_id, e)
        return False


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    """Get a single client by ID."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, display_name, os_type, app_version, last_seen_at, created_at "
            "FROM clients WHERE id = %s",
            (client_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get client %s: %s", client_id, e)
        return None


def list_clients() -> List[Dict[str, Any]]:
    """List all registered clients, most recently seen first."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, display_name, os_type, app_version, last_seen_at, created_at "
            "FROM clients ORDER BY last_seen_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list clients: %s", e)
        return []


# ---------------------------------------------------------------------------
# Desktop-side helpers
# ---------------------------------------------------------------------------


def generate_client_id() -> str:
    """Generate a new unique client ID."""
    return str(uuid.uuid4())


def get_os_type() -> str:
    """Return a normalized OS type string."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system in ("linux", "windows"):
        return system
    return system or "unknown"


def get_default_display_name() -> str:
    """Generate a human-friendly default display name."""
    hostname = platform.node() or "Unknown"
    os_type = get_os_type()
    return f"{hostname} ({os_type})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLUMNS = ("id", "display_name", "os_type", "app_version", "last_seen_at", "created_at")


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    for key in ("last_seen_at", "created_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    return d
