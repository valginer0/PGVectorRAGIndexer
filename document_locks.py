"""
Document Locks module (#3 Multi-User, Phase 1).

Provides conflict-safe indexing by preventing two clients from
indexing the same document simultaneously.  Locks have a TTL
(default 10 minutes) and auto-expire if a client dies.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TTL_MINUTES = 10


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


_COLUMNS = ("id", "source_uri", "client_id", "locked_at", "expires_at", "lock_reason")


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    for ts_key in ("locked_at", "expires_at"):
        ts = d.get(ts_key)
        if isinstance(ts, datetime):
            d[ts_key] = ts.isoformat()
    return d


# ---------------------------------------------------------------------------
# Acquire / Release
# ---------------------------------------------------------------------------


def acquire_lock(
    source_uri: str,
    client_id: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    lock_reason: str = "indexing",
) -> Dict[str, Any]:
    """Try to acquire a lock on a document.

    If the document is already locked by another client and the lock
    has not expired, returns an error dict with the current holder info.

    If the document is locked but the lock has expired, the old lock
    is replaced.

    Args:
        source_uri: The document path to lock.
        client_id: The client requesting the lock.
        ttl_minutes: Lock duration in minutes.
        lock_reason: Why the lock is being acquired.

    Returns:
        Dict with 'ok': True and lock info on success,
        or 'ok': False with 'error' and 'holder' on conflict.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # First, clean up expired locks for this source_uri
        cur.execute(
            "DELETE FROM document_locks WHERE source_uri = %s AND expires_at < now()",
            (source_uri,),
        )

        # Check if there's an active lock
        cur.execute(
            "SELECT {cols} FROM document_locks WHERE source_uri = %s".format(
                cols=", ".join(_COLUMNS)
            ),
            (source_uri,),
        )
        existing = cur.fetchone()

        if existing:
            existing_dict = _row_to_dict(existing)
            if existing_dict["client_id"] == client_id:
                # Same client — extend the lock
                cur.execute(
                    """
                    UPDATE document_locks
                    SET expires_at = now() + interval '%s minutes',
                        locked_at = now(),
                        lock_reason = %s
                    WHERE source_uri = %s AND client_id = %s
                    RETURNING {cols}
                    """.format(cols=", ".join(_COLUMNS)),
                    (ttl_minutes, lock_reason, source_uri, client_id),
                )
                row = cur.fetchone()
                conn.commit()
                cur.close()
                conn.close()
                return {"ok": True, "lock": _row_to_dict(row), "extended": True}
            else:
                # Different client holds the lock
                conn.close()
                return {
                    "ok": False,
                    "error": (
                        f"Document is being indexed by client '{existing_dict['client_id']}' "
                        f"(lock expires at {existing_dict['expires_at']})"
                    ),
                    "holder": existing_dict,
                }

        # No active lock — create one
        lock_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO document_locks (id, source_uri, client_id, expires_at, lock_reason)
            VALUES (%s, %s, %s, now() + interval '%s minutes', %s)
            RETURNING {cols}
            """.format(cols=", ".join(_COLUMNS)),
            (lock_id, source_uri, client_id, ttl_minutes, lock_reason),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {"ok": True, "lock": _row_to_dict(row), "extended": False}

    except Exception as e:
        logger.warning("Failed to acquire lock for '%s': %s", source_uri, e)
        return {"ok": False, "error": f"Lock acquisition failed: {str(e)}"}


def release_lock(source_uri: str, client_id: str) -> bool:
    """Release a lock on a document.

    Only the client that holds the lock can release it.

    Returns:
        True if the lock was released, False otherwise.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM document_locks WHERE source_uri = %s AND client_id = %s",
            (source_uri, client_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning("Failed to release lock for '%s': %s", source_uri, e)
        return False


def force_release_lock(source_uri: str) -> bool:
    """Force-release a lock regardless of who holds it (admin operation).

    Returns:
        True if a lock was removed, False otherwise.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM document_locks WHERE source_uri = %s",
            (source_uri,),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning("Failed to force-release lock for '%s': %s", source_uri, e)
        return False


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def check_lock(source_uri: str) -> Optional[Dict[str, Any]]:
    """Check if a document is currently locked.

    Returns:
        Lock info dict if locked (and not expired), None otherwise.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT {cols} FROM document_locks
            WHERE source_uri = %s AND expires_at > now()
            """.format(cols=", ".join(_COLUMNS)),
            (source_uri,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to check lock for '%s': %s", source_uri, e)
        return None


def list_locks(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all active (non-expired) locks.

    Args:
        client_id: Optional filter by client.

    Returns:
        List of lock dicts.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        sql = "SELECT {cols} FROM document_locks WHERE expires_at > now()".format(
            cols=", ".join(_COLUMNS)
        )
        params: list = []
        if client_id:
            sql += " AND client_id = %s"
            params.append(client_id)
        sql += " ORDER BY locked_at DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list locks: %s", e)
        return []


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_expired_locks() -> int:
    """Remove all expired locks.

    Returns:
        Number of expired locks removed.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM document_locks WHERE expires_at < now()")
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if deleted > 0:
            logger.info("Cleaned up %d expired document locks", deleted)
        return deleted
    except Exception as e:
        logger.warning("Failed to cleanup expired locks: %s", e)
        return 0
