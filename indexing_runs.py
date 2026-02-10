"""
Indexing runs tracking for the Health Dashboard (#4).

Records each indexing operation with timing, file counts, and errors.
Provides query functions for the API and UI.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def start_run(
    trigger: str = "manual",
    source_uri: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    client_id: Optional[str] = None,
) -> str:
    """Record the start of an indexing run.

    Args:
        trigger: What initiated the run ('manual', 'upload', 'cli', 'scheduled', 'api').
        source_uri: Optional source being indexed (file path, folder, etc.).
        metadata: Optional extra metadata to store with the run.
        client_id: Optional client identity that initiated the run (#8).

    Returns:
        The UUID of the new run (as a string).
    """
    run_id = str(uuid.uuid4())
    db = get_db_manager()
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO indexing_runs (id, trigger, source_uri, metadata, client_id)
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                    """,
                    (run_id, trigger, source_uri, _json_dumps(metadata or {}), client_id),
                )
                conn.commit()
        logger.debug("Started indexing run %s (trigger=%s, client=%s)", run_id, trigger, client_id)
    except Exception as e:
        logger.warning("Failed to record indexing run start: %s", e)
    return run_id


def complete_run(
    run_id: str,
    *,
    status: str = "success",
    files_scanned: int = 0,
    files_added: int = 0,
    files_updated: int = 0,
    files_skipped: int = 0,
    files_failed: int = 0,
    errors: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Record the completion of an indexing run.

    Args:
        run_id: The UUID returned by start_run().
        status: Final status ('success', 'partial', 'failed').
        files_scanned: Total files examined.
        files_added: New files indexed.
        files_updated: Existing files re-indexed.
        files_skipped: Files skipped (already indexed, unsupported, etc.).
        files_failed: Files that failed to index.
        errors: List of error dicts [{source_uri, error, ...}].
    """
    db = get_db_manager()
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE indexing_runs
                    SET completed_at = now(),
                        status = %s,
                        files_scanned = %s,
                        files_added = %s,
                        files_updated = %s,
                        files_skipped = %s,
                        files_failed = %s,
                        errors = %s::jsonb
                    WHERE id = %s
                    """,
                    (
                        status,
                        files_scanned,
                        files_added,
                        files_updated,
                        files_skipped,
                        files_failed,
                        _json_dumps(errors or []),
                        run_id,
                    ),
                )
                conn.commit()
        logger.debug("Completed indexing run %s (status=%s)", run_id, status)
    except Exception as e:
        logger.warning("Failed to record indexing run completion: %s", e)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_recent_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """Get the most recent indexing runs.

    Args:
        limit: Maximum number of runs to return.

    Returns:
        List of run dicts, newest first.
    """
    db = get_db_manager()
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, started_at, completed_at, status, trigger,
                           files_scanned, files_added, files_updated,
                           files_skipped, files_failed, errors,
                           source_uri, metadata
                    FROM indexing_runs
                    ORDER BY started_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [_row_to_dict(columns, row) for row in rows]
    except Exception as e:
        logger.error("Failed to query indexing runs: %s", e)
        return []


def get_run_by_id(run_id: str) -> Optional[Dict[str, Any]]:
    """Get a single indexing run by ID."""
    db = get_db_manager()
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, started_at, completed_at, status, trigger,
                           files_scanned, files_added, files_updated,
                           files_skipped, files_failed, errors,
                           source_uri, metadata
                    FROM indexing_runs
                    WHERE id = %s
                    """,
                    (run_id,),
                )
                columns = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                if row:
                    return _row_to_dict(columns, row)
                return None
    except Exception as e:
        logger.error("Failed to query indexing run %s: %s", run_id, e)
        return None


def get_run_summary() -> Dict[str, Any]:
    """Get aggregate statistics about indexing runs.

    Returns:
        Dict with total_runs, successful, failed, partial,
        total_files_added, total_files_updated, last_run_at.
    """
    db = get_db_manager()
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_runs,
                        COUNT(*) FILTER (WHERE status = 'success') AS successful,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                        COUNT(*) FILTER (WHERE status = 'partial') AS partial,
                        COALESCE(SUM(files_added), 0) AS total_files_added,
                        COALESCE(SUM(files_updated), 0) AS total_files_updated,
                        MAX(started_at) AS last_run_at
                    FROM indexing_runs
                    WHERE status != 'running'
                """)
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except Exception as e:
        logger.error("Failed to get run summary: %s", e)
        return {
            "total_runs": 0,
            "successful": 0,
            "failed": 0,
            "partial": 0,
            "total_files_added": 0,
            "total_files_updated": 0,
            "last_run_at": None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_dumps(obj: Any) -> str:
    """Serialize to JSON string for PostgreSQL."""
    import json
    return json.dumps(obj, default=str)


def _row_to_dict(columns: List[str], row: tuple) -> Dict[str, Any]:
    """Convert a database row to a dict with serializable values."""
    d = dict(zip(columns, row))
    # Convert datetimes to ISO strings
    for key in ("started_at", "completed_at", "last_run_at"):
        if key in d and d[key] is not None:
            d[key] = d[key].isoformat() if hasattr(d[key], "isoformat") else str(d[key])
    # Convert UUID to string
    if "id" in d:
        d["id"] = str(d["id"])
    return d
