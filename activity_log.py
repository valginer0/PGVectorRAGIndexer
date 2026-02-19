"""
Activity and Audit Log module (#10).

Tracks who indexed what and when for trust and debugging.
Provides logging, querying, CSV export, and retention policy functions.
"""

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection_raw()


_COLUMNS = ("id", "ts", "client_id", "user_id", "action", "details",
            "executor_scope", "executor_id", "root_id", "run_id")


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    ts = d.get("ts")
    if isinstance(ts, datetime):
        d["ts"] = ts.isoformat()
    return d


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_activity(
    action: str,
    *,
    client_id: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    executor_scope: Optional[str] = None,
    executor_id: Optional[str] = None,
    root_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[str]:
    """Record an activity log entry.

    Args:
        action: Action type (e.g. 'index_start', 'index_complete',
                'delete', 'upload', 'search', 'client_register').
        client_id: Optional client that performed the action.
        user_id: Optional user (for future multi-user #3).
        details: Optional extra details as a JSON-serializable dict.
        executor_scope: Optional 'client' or 'server' (#6b).
        executor_id: Optional executor identity (#6b).
        root_id: Optional watched folder root_id (#6b).
        run_id: Optional indexing run ID (#6b).

    Returns:
        The UUID of the log entry, or None on failure.
    """
    entry_id = str(uuid.uuid4())
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO activity_log
                (id, client_id, user_id, action, details,
                 executor_scope, executor_id, root_id, run_id)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (entry_id, client_id, user_id, action, json.dumps(details or {}),
             executor_scope, executor_id, root_id, run_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return entry_id
    except Exception as e:
        logger.warning("Failed to log activity '%s': %s", action, e)
        return None


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


def get_recent(
    limit: int = 50,
    offset: int = 0,
    client_id: Optional[str] = None,
    action: Optional[str] = None,
    root_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query recent activity log entries.

    Args:
        limit: Max entries to return.
        offset: Pagination offset.
        client_id: Optional filter by client.
        action: Optional filter by action type.
        root_id: Optional filter by watched folder root_id.
        run_id: Optional filter by indexing run ID.

    Returns:
        List of activity dicts, newest first.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        sql = "SELECT {cols} FROM activity_log".format(cols=", ".join(_COLUMNS))
        conditions = []
        params: list = []
        if client_id:
            conditions.append("client_id = %s")
            params.append(client_id)
        if action:
            conditions.append("action = %s")
            params.append(action)
        if root_id:
            conditions.append("root_id = %s")
            params.append(root_id)
        if run_id:
            conditions.append("run_id = %s")
            params.append(run_id)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY ts DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to query activity log: %s", e)
        return []


def get_activity_count(
    client_id: Optional[str] = None,
    action: Optional[str] = None,
) -> int:
    """Get total count of activity log entries (for pagination)."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        sql = "SELECT COUNT(*) FROM activity_log"
        conditions = []
        params: list = []
        if client_id:
            conditions.append("client_id = %s")
            params.append(client_id)
        if action:
            conditions.append("action = %s")
            params.append(action)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        cur.execute(sql, params)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("Failed to count activity log: %s", e)
        return 0


def get_action_types() -> List[str]:
    """Get distinct action types in the log."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT action FROM activity_log ORDER BY action")
        types = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return types
    except Exception as e:
        logger.warning("Failed to get action types: %s", e)
        return []


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def export_csv(
    client_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 10000,
) -> str:
    """Export activity log entries as a CSV string.

    Returns:
        CSV-formatted string.
    """
    entries = get_recent(limit=limit, client_id=client_id, action=action)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "ts", "client_id", "user_id", "action", "details",
                    "executor_scope", "executor_id", "root_id", "run_id"],
    )
    writer.writeheader()
    for entry in entries:
        row = dict(entry)
        if isinstance(row.get("details"), dict):
            row["details"] = json.dumps(row["details"])
        writer.writerow(row)
    return output.getvalue()


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def apply_retention(days: int) -> int:
    """Delete activity log entries older than N days.

    Returns:
        Number of entries deleted.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM activity_log WHERE ts < now() - interval '%s days'",
            (days,),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Retention: deleted %d activity log entries older than %d days", deleted, days)
        return deleted
    except Exception as e:
        logger.warning("Failed to apply retention: %s", e)
        return 0
