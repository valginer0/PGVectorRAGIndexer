"""
Watched Folders module (#6).

CRUD operations for watched folders and scan triggering.
Each watched folder is a directory path that the system monitors
and automatically indexes on a cron schedule.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_COLUMNS = (
    "id", "folder_path", "enabled", "schedule_cron",
    "last_scanned_at", "last_run_id", "client_id",
    "created_at", "updated_at", "metadata",
)


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    for key in ("last_scanned_at", "created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    # Ensure id is a string (UUID comes back as uuid.UUID from psycopg2)
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    if d.get("last_run_id") is not None:
        d["last_run_id"] = str(d["last_run_id"])
    return d


def add_folder(
    folder_path: str,
    schedule_cron: str = "0 */6 * * *",
    client_id: Optional[str] = None,
    enabled: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Add a new watched folder.

    Returns the created row as a dict, or None on failure.
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO watched_folders
                (folder_path, schedule_cron, client_id, enabled, metadata)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (folder_path) DO UPDATE SET
                schedule_cron = EXCLUDED.schedule_cron,
                client_id = EXCLUDED.client_id,
                enabled = EXCLUDED.enabled,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING {cols}
            """.format(cols=", ".join(_COLUMNS)),
            (folder_path, schedule_cron, client_id, enabled,
             json.dumps(metadata or {})),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to add watched folder %s: %s", folder_path, e)
        return None


def remove_folder(folder_id: str) -> bool:
    """Remove a watched folder by ID. Returns True on success."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM watched_folders WHERE id = %s", (folder_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.warning("Failed to remove watched folder %s: %s", folder_id, e)
        return False


def update_folder(
    folder_id: str,
    *,
    enabled: Optional[bool] = None,
    schedule_cron: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a watched folder's settings. Returns updated row or None."""
    sets = []
    params = []
    if enabled is not None:
        sets.append("enabled = %s")
        params.append(enabled)
    if schedule_cron is not None:
        sets.append("schedule_cron = %s")
        params.append(schedule_cron)
    if not sets:
        return get_folder(folder_id)

    sets.append("updated_at = now()")
    params.append(folder_id)

    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE watched_folders SET {sets} WHERE id = %s RETURNING {cols}".format(
                sets=", ".join(sets), cols=", ".join(_COLUMNS)
            ),
            params,
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to update watched folder %s: %s", folder_id, e)
        return None


def get_folder(folder_id: str) -> Optional[Dict[str, Any]]:
    """Get a single watched folder by ID."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT {cols} FROM watched_folders WHERE id = %s".format(
                cols=", ".join(_COLUMNS)
            ),
            (folder_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get watched folder %s: %s", folder_id, e)
        return None


def list_folders(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """List watched folders, optionally filtering to enabled only."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        sql = "SELECT {cols} FROM watched_folders".format(cols=", ".join(_COLUMNS))
        if enabled_only:
            sql += " WHERE enabled = true"
        sql += " ORDER BY created_at"
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to list watched folders: %s", e)
        return []


def mark_scanned(folder_id: str, run_id: Optional[str] = None) -> bool:
    """Update last_scanned_at (and optionally last_run_id) after a scan."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE watched_folders
            SET last_scanned_at = now(), last_run_id = %s, updated_at = now()
            WHERE id = %s
            """,
            (run_id, folder_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.warning("Failed to mark folder %s as scanned: %s", folder_id, e)
        return False


# ---------------------------------------------------------------------------
# Scan trigger
# ---------------------------------------------------------------------------


def scan_folder(folder_path: str, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Trigger an indexing scan of a folder.

    Uses the existing indexer to walk the folder and index new/changed files.
    Returns a summary dict with counts.
    """
    import os
    from indexing_runs import start_run, complete_run

    run_id = start_run(trigger="scheduled", source_uri=folder_path, client_id=client_id)
    scanned = 0
    added = 0
    failed = 0
    errors = []

    try:
        from indexer_v2 import DocumentIndexer
        from database import get_db_manager
        from embeddings import get_embedding_service

        db = get_db_manager()
        embedding_service = get_embedding_service()
        indexer = DocumentIndexer(db, embedding_service)

        if not os.path.isdir(folder_path):
            complete_run(
                run_id,
                status="failed",
                errors=[{"source_uri": folder_path, "error": "Directory not found"}],
            )
            return {
                "run_id": run_id,
                "status": "failed",
                "error": f"Directory not found: {folder_path}",
            }

        for root, _dirs, files in os.walk(folder_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                scanned += 1
                try:
                    indexer.index_document(fpath)
                    added += 1
                except Exception as e:
                    failed += 1
                    errors.append({"source_uri": fpath, "error": str(e)})

        final_status = "success" if failed == 0 else "partial"
        complete_run(
            run_id,
            status=final_status,
            files_scanned=scanned,
            files_added=added,
            files_failed=failed,
            errors=errors if errors else None,
        )
        return {
            "run_id": run_id,
            "status": final_status,
            "files_scanned": scanned,
            "files_added": added,
            "files_failed": failed,
        }
    except Exception as e:
        logger.error("Scan of %s failed: %s", folder_path, e)
        complete_run(
            run_id,
            status="failed",
            files_scanned=scanned,
            files_added=added,
            files_failed=failed,
            errors=[{"source_uri": folder_path, "error": str(e)}] + errors,
        )
        return {
            "run_id": run_id,
            "status": "failed",
            "error": str(e),
            "files_scanned": scanned,
            "files_added": added,
            "files_failed": failed,
        }
