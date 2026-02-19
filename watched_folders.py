"""
Watched Folders module (#6 + #6b).

CRUD operations for watched folders and scan triggering.
Each watched folder is a directory path that the system monitors
and automatically indexes on a cron schedule.

#6b additions: execution scope (client/server), executor identity,
normalized paths, scan watermarks, failure tracking, and scope transitions.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    return get_db_manager().get_connection_raw()


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


def normalize_folder_path(path: str) -> str:
    """Normalize a folder path for scoped uniqueness comparison.

    - Strips leading/trailing whitespace
    - Strips trailing slashes (except root '/')
    - Collapses repeated slashes
    - Lowercases on case-insensitive platforms (Windows)
    """
    p = path.strip()
    if not p:
        return p
    # Collapse repeated slashes
    while "//" in p:
        p = p.replace("//", "/")
    # Strip trailing slash (keep root)
    if len(p) > 1:
        p = p.rstrip("/")
    # Lowercase on Windows only
    if os.name == "nt":
        p = p.lower()
    return p


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_COLUMNS = (
    "id", "folder_path", "enabled", "schedule_cron",
    "last_scanned_at", "last_run_id", "client_id",
    "created_at", "updated_at", "metadata",
    # #6b columns
    "execution_scope", "executor_id", "normalized_folder_path",
    "root_id", "last_scan_started_at", "last_scan_completed_at",
    "last_successful_scan_at", "last_error_at",
    "consecutive_failures", "paused", "max_concurrency",
)


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row tuple to a dict with ISO timestamps."""
    d = dict(zip(_COLUMNS, row))
    for key in (
        "last_scanned_at", "created_at", "updated_at",
        "last_scan_started_at", "last_scan_completed_at",
        "last_successful_scan_at", "last_error_at",
    ):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    # Ensure UUIDs are strings
    for key in ("id", "last_run_id", "root_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    return d


def add_folder(
    folder_path: str,
    schedule_cron: str = "0 */6 * * *",
    client_id: Optional[str] = None,
    enabled: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    execution_scope: str = "client",
    executor_id: Optional[str] = None,
    paused: bool = False,
    max_concurrency: int = 1,
) -> Optional[Dict[str, Any]]:
    """Add a new watched folder.

    Returns the created row as a dict, or None on failure.

    For client scope: executor_id defaults to client_id if not provided.
    For server scope: executor_id must be None.
    """
    if execution_scope not in ("client", "server"):
        raise ValueError(f"Invalid execution_scope: {execution_scope!r}")

    norm_path = normalize_folder_path(folder_path)

    # Enforce scope/executor invariant
    if execution_scope == "client":
        if executor_id is None:
            executor_id = client_id
        if executor_id is None:
            raise ValueError(
                "executor_id (or client_id) is required for client-scope roots"
            )
    else:
        executor_id = None  # Server scope: no executor

    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Use different conflict targets based on scope.
        # The partial unique indexes mean we can't use a single ON CONFLICT.
        # Instead, check for conflict manually and upsert.
        if execution_scope == "client":
            conflict_check = """
                SELECT id FROM watched_folders
                WHERE executor_id = %s
                  AND normalized_folder_path = %s
                  AND execution_scope = 'client'
            """
            cur.execute(conflict_check, (executor_id, norm_path))
        else:
            conflict_check = """
                SELECT id FROM watched_folders
                WHERE normalized_folder_path = %s
                  AND execution_scope = 'server'
            """
            cur.execute(conflict_check, (norm_path,))

        existing = cur.fetchone()

        if existing:
            # Update existing row
            existing_id = str(existing[0])
            cur.execute(
                """
                UPDATE watched_folders SET
                    folder_path = %s,
                    schedule_cron = %s,
                    client_id = %s,
                    enabled = %s,
                    metadata = %s::jsonb,
                    normalized_folder_path = %s,
                    paused = %s,
                    max_concurrency = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING {cols}
                """.format(cols=", ".join(_COLUMNS)),
                (folder_path, schedule_cron, client_id, enabled,
                 json.dumps(metadata or {}), norm_path,
                 paused, max_concurrency, existing_id),
            )
        else:
            # Insert new row
            cur.execute(
                """
                INSERT INTO watched_folders
                    (folder_path, schedule_cron, client_id, enabled, metadata,
                     execution_scope, executor_id, normalized_folder_path,
                     paused, max_concurrency)
                VALUES (%s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s, %s)
                RETURNING {cols}
                """.format(cols=", ".join(_COLUMNS)),
                (folder_path, schedule_cron, client_id, enabled,
                 json.dumps(metadata or {}),
                 execution_scope, executor_id, norm_path,
                 paused, max_concurrency),
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
    paused: Optional[bool] = None,
    max_concurrency: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Update a watched folder's settings. Returns updated row or None.

    Note: execution_scope cannot be changed here. Use transition_scope().
    """
    sets = []
    params = []
    if enabled is not None:
        sets.append("enabled = %s")
        params.append(enabled)
    if schedule_cron is not None:
        sets.append("schedule_cron = %s")
        params.append(schedule_cron)
    if paused is not None:
        sets.append("paused = %s")
        params.append(paused)
    if max_concurrency is not None:
        sets.append("max_concurrency = %s")
        params.append(max_concurrency)
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


def get_folder_by_root_id(root_id: str) -> Optional[Dict[str, Any]]:
    """Get a single watched folder by root_id."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT {cols} FROM watched_folders WHERE root_id = %s".format(
                cols=", ".join(_COLUMNS)
            ),
            (root_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to get watched folder by root_id %s: %s", root_id, e)
        return None


def list_folders(
    enabled_only: bool = False,
    *,
    execution_scope: Optional[str] = None,
    executor_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List watched folders with optional scope/executor filtering.

    Args:
        enabled_only: Only return enabled folders.
        execution_scope: Filter by 'client' or 'server'.
        executor_id: Filter by executor (client-scope roots).
    """
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        conditions = []
        params: list = []
        if enabled_only:
            conditions.append("enabled = true")
        if execution_scope is not None:
            conditions.append("execution_scope = %s")
            params.append(execution_scope)
        if executor_id is not None:
            conditions.append("executor_id = %s")
            params.append(executor_id)

        sql = "SELECT {cols} FROM watched_folders".format(
            cols=", ".join(_COLUMNS)
        )
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at"

        cur.execute(sql, params)
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
# Scan watermarks (#6b)
# ---------------------------------------------------------------------------


def update_scan_watermarks(
    folder_id: str,
    *,
    started: bool = False,
    completed: bool = False,
    success: bool = False,
    error: bool = False,
    reset_failures: bool = False,
) -> bool:
    """Update scan timing watermarks and failure counters.

    Args:
        folder_id: The watched folder ID.
        started: Set last_scan_started_at to now().
        completed: Set last_scan_completed_at to now().
        success: Set last_successful_scan_at to now() and reset consecutive_failures.
        error: Set last_error_at to now() and increment consecutive_failures.
        reset_failures: Reset consecutive_failures to 0.
    """
    sets = []
    if started:
        sets.append("last_scan_started_at = now()")
    if completed:
        sets.append("last_scan_completed_at = now()")
    if success:
        sets.append("last_successful_scan_at = now()")
        sets.append("consecutive_failures = 0")
    if error:
        sets.append("last_error_at = now()")
        sets.append("consecutive_failures = consecutive_failures + 1")
    if reset_failures:
        sets.append("consecutive_failures = 0")
    if not sets:
        return True

    sets.append("updated_at = now()")

    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE watched_folders SET {sets} WHERE id = %s".format(
                sets=", ".join(sets)
            ),
            (folder_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.warning(
            "Failed to update scan watermarks for %s: %s", folder_id, e
        )
        return False


# ---------------------------------------------------------------------------
# Scope transitions (#6b)
# ---------------------------------------------------------------------------


def transition_scope(
    folder_id: str,
    target_scope: str,
    executor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition a watched folder between client and server scope.

    Performs in-place update preserving root_id.
    Returns {"ok": True, "folder": <dict>} on success,
    or {"ok": False, "error": <str>} on conflict/failure.
    """
    if target_scope not in ("client", "server"):
        return {"ok": False, "error": f"Invalid target scope: {target_scope!r}"}

    if target_scope == "client" and not executor_id:
        return {"ok": False, "error": "executor_id is required for client scope"}

    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        # Get current folder
        cur.execute(
            "SELECT {cols} FROM watched_folders WHERE id = %s FOR UPDATE".format(
                cols=", ".join(_COLUMNS)
            ),
            (folder_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return {"ok": False, "error": "Folder not found"}

        folder = _row_to_dict(row)

        if folder["execution_scope"] == target_scope:
            cur.close()
            conn.close()
            return {"ok": False, "error": f"Already in {target_scope} scope"}

        norm_path = folder["normalized_folder_path"]

        # Preflight conflict check
        if target_scope == "client":
            cur.execute(
                """
                SELECT id FROM watched_folders
                WHERE executor_id = %s
                  AND normalized_folder_path = %s
                  AND execution_scope = 'client'
                  AND id != %s
                """,
                (executor_id, norm_path, folder_id),
            )
        else:
            cur.execute(
                """
                SELECT id FROM watched_folders
                WHERE normalized_folder_path = %s
                  AND execution_scope = 'server'
                  AND id != %s
                """,
                (norm_path, folder_id),
            )

        conflict = cur.fetchone()
        if conflict:
            cur.close()
            conn.close()
            return {
                "ok": False,
                "error": f"Conflict: path already exists in {target_scope} scope",
            }

        # Perform transition
        new_executor = executor_id if target_scope == "client" else None
        cur.execute(
            """
            UPDATE watched_folders SET
                execution_scope = %s,
                executor_id = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING {cols}
            """.format(cols=", ".join(_COLUMNS)),
            (target_scope, new_executor, folder_id),
        )
        updated = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {"ok": True, "folder": _row_to_dict(updated) if updated else folder}
    except Exception as e:
        logger.warning("Failed to transition scope for %s: %s", folder_id, e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Scan trigger
# ---------------------------------------------------------------------------


def scan_folder(
    folder_path: str,
    client_id: Optional[str] = None,
    root_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Trigger an indexing scan of a folder.

    Uses the existing indexer to walk the folder and index new/changed files.
    Returns a summary dict with counts.

    Args:
        folder_path: Directory to scan.
        client_id: Optional client identifier.
        root_id: Optional watched-folder root_id for canonical key backfill.
        dry_run: If True, report what would happen without making changes.
    """
    import os

    # -- Dry-run mode: walk and report without mutations ---------------------
    if dry_run:
        return _dry_run_scan(folder_path)

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

        # Backfill canonical source keys if root_id is known
        if root_id:
            _backfill_canonical_keys(root_id, folder_path)

        # Quarantine/restore stale chunks
        _quarantine_missing_sources(folder_path)

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


def _dry_run_scan(folder_path: str) -> Dict[str, Any]:
    """Walk a folder and report what would happen without making DB changes."""
    import os

    if not os.path.isdir(folder_path):
        return {
            "dry_run": True,
            "status": "failed",
            "error": f"Directory not found: {folder_path}",
        }

    would_index = []
    for root, _dirs, files in os.walk(folder_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            would_index.append(fpath)

    # Check for previously indexed files that are now missing
    would_quarantine = []
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        prefix = folder_path.replace("\\", "/").rstrip("/") + "/"
        cur.execute(
            "SELECT DISTINCT source_uri FROM document_chunks WHERE source_uri LIKE %s",
            (prefix + "%",),
        )
        indexed_uris = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()

        current_files = {f.replace("\\", "/") for f in would_index}
        for uri in indexed_uris:
            normalized = uri.replace("\\", "/")
            if normalized not in current_files:
                would_quarantine.append(uri)
    except Exception as e:
        logger.warning("Dry-run quarantine check failed: %s", e)

    return {
        "dry_run": True,
        "status": "success",
        "would_index": would_index,
        "would_quarantine": would_quarantine,
        "total_files": len(would_index),
        "total_quarantine": len(would_quarantine),
    }


def _backfill_canonical_keys(root_id: str, folder_path: str) -> None:
    """Backfill canonical_source_key for chunks under a watched root."""
    try:
        folder = get_folder_by_root_id(root_id)
        if not folder:
            logger.warning("Cannot backfill canonical keys: root %s not found", root_id)
            return

        scope = folder.get("execution_scope", "client")
        identity = folder.get("executor_id") if scope == "client" else root_id

        from canonical_identity import bulk_set_canonical_keys
        count = bulk_set_canonical_keys(root_id, folder_path, scope, identity)
        if count > 0:
            logger.info("Backfilled %d canonical keys for root %s", count, root_id)
    except Exception as e:
        logger.warning("Canonical key backfill failed for root %s: %s", root_id, e)


def _quarantine_missing_sources(folder_path: str) -> None:
    """After a scan, quarantine chunks whose source files no longer exist
    and restore chunks whose source files have reappeared."""
    import os

    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        prefix = folder_path.replace("\\", "/").rstrip("/") + "/"
        cur.execute(
            "SELECT DISTINCT source_uri, (quarantined_at IS NOT NULL) AS is_quarantined "
            "FROM document_chunks WHERE source_uri LIKE %s",
            (prefix + "%",),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        from quarantine import quarantine_chunks, restore_chunks

        quarantined_count = 0
        restored_count = 0
        for source_uri, is_quarantined in rows:
            file_exists = os.path.isfile(source_uri)
            if not file_exists and not is_quarantined:
                quarantine_chunks(source_uri, "source_file_missing")
                quarantined_count += 1
            elif file_exists and is_quarantined:
                restore_chunks(source_uri)
                restored_count += 1

        if quarantined_count > 0:
            logger.info("Quarantined %d missing sources under %s", quarantined_count, folder_path)
        if restored_count > 0:
            logger.info("Restored %d reappeared sources under %s", restored_count, folder_path)

    except Exception as e:
        logger.warning("Quarantine scan failed for %s: %s", folder_path, e)
