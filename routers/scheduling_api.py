"""
Watched Folder and Scheduler management routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from auth import require_api_key

logger = logging.getLogger(__name__)

scheduling_router = APIRouter(tags=["Scheduling & Automation"])


@scheduling_router.get("/watched-folders", dependencies=[Depends(require_api_key)])
async def list_watched_folders(
    enabled_only: bool = Query(default=False),
    execution_scope: Optional[str] = Query(default=None, description="Filter by scope: client or server"),
    executor_id: Optional[str] = Query(default=None, description="Filter by executor (client scope)"),
):
    """List all watched folders."""
    from watched_folders import list_folders
    try:
        folders = list_folders(
            enabled_only=enabled_only,
            execution_scope=execution_scope,
            executor_id=executor_id,
        )
        return {"folders": folders, "count": len(folders)}
    except Exception as e:
        logger.error(f"Failed to list watched folders: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list watched folders: {str(e)}",
        )


@scheduling_router.post("/watched-folders", dependencies=[Depends(require_api_key)])
async def add_watched_folder(request: Request):
    """Add or update a watched folder."""
    from watched_folders import add_folder
    try:
        body = await request.json()
        folder_path = body.get("folder_path")
        if not folder_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="folder_path is required",
            )

        execution_scope = body.get("execution_scope", "client")

        if execution_scope == "server":
            import os as _os
            if not _os.path.isdir(folder_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Server-scope root path does not exist or is not accessible: {folder_path}",
                )

        result = add_folder(
            folder_path=folder_path,
            schedule_cron=body.get("schedule_cron", "0 */6 * * *"),
            client_id=body.get("client_id"),
            enabled=body.get("enabled", True),
            metadata=body.get("metadata"),
            execution_scope=execution_scope,
            executor_id=body.get("executor_id"),
            paused=body.get("paused", False),
            max_concurrency=body.get("max_concurrency", 1),
        )
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add watched folder",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to add watched folder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add watched folder: {str(e)}",
        )


@scheduling_router.put("/watched-folders/{folder_id}", dependencies=[Depends(require_api_key)])
async def update_watched_folder(folder_id: str, request: Request):
    """Update a watched folder's settings."""
    from watched_folders import update_folder
    try:
        body = await request.json()
        if "execution_scope" in body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="execution_scope cannot be changed via update. Use /watched-folders/{id}/transition-scope.",
            )

        result = update_folder(
            folder_id,
            enabled=body.get("enabled"),
            schedule_cron=body.get("schedule_cron"),
            paused=body.get("paused"),
            max_concurrency=body.get("max_concurrency"),
        )
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watched folder not found: {folder_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update watched folder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update watched folder: {str(e)}",
        )


@scheduling_router.delete("/watched-folders/{folder_id}", dependencies=[Depends(require_api_key)])
async def delete_watched_folder(folder_id: str):
    """Remove a watched folder."""
    from watched_folders import remove_folder
    try:
        if remove_folder(folder_id):
            return {"ok": True}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watched folder not found: {folder_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove watched folder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove watched folder: {str(e)}",
        )


@scheduling_router.post("/watched-folders/{folder_id}/scan", dependencies=[Depends(require_api_key)])
async def scan_watched_folder(folder_id: str, request: Request, dry_run: bool = Query(default=False)):
    """Trigger an immediate scan of a watched folder."""
    from watched_folders import get_folder, scan_folder, mark_scanned
    try:
        folder = get_folder(folder_id)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Watched folder not found: {folder_id}",
            )

        client_id = None
        try:
            body = await request.json()
            client_id = body.get("client_id")
        except Exception:
            pass

        scope = folder.get("execution_scope", "client")
        if scope == "server" and client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot scan server-scope root '{folder['folder_path']}' "
                    f"from a client (client_id={client_id}). "
                    f"Server-scope roots are scanned by the server scheduler."
                ),
            )
        if scope == "client":
            executor = folder.get("executor_id")
            if client_id and executor and client_id != executor:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Client '{client_id}' cannot scan root owned by "
                        f"executor '{executor}'."
                    ),
                )

        result = scan_folder(
            folder["folder_path"],
            client_id=client_id,
            root_id=folder.get("root_id"),
            dry_run=dry_run,
        )
        if not dry_run and result.get("run_id"):
            mark_scanned(folder_id, run_id=result["run_id"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan watched folder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan: {str(e)}",
        )


@scheduling_router.post("/watched-folders/{folder_id}/transition-scope", dependencies=[Depends(require_api_key)])
async def transition_folder_scope(folder_id: str, request: Request):
    """Transition a watched folder between client and server scope."""
    from watched_folders import transition_scope
    try:
        body = await request.json()
        target_scope = body.get("target_scope")
        if target_scope not in ("client", "server"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_scope must be 'client' or 'server'",
            )

        if target_scope == "server":
            from watched_folders import get_folder
            folder = get_folder(folder_id)
            if folder:
                import os as _os
                if not _os.path.isdir(folder["folder_path"]):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Server-scope root path not accessible: {folder['folder_path']}",
                    )

        result = transition_scope(
            folder_id,
            target_scope=target_scope,
            executor_id=body.get("executor_id"),
        )
        if result["ok"]:
            return result["folder"]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result["error"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to transition scope: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to transition scope: {str(e)}",
        )


@scheduling_router.get("/scheduler/status", tags=["Scheduler Admin"], dependencies=[Depends(require_api_key)])
async def get_scheduler_status():
    """Get server scheduler status."""
    from server_scheduler import get_server_scheduler
    scheduler = get_server_scheduler()
    return scheduler.get_status()


@scheduling_router.get("/scheduler/roots/{root_id}/status", tags=["Scheduler Admin"], dependencies=[Depends(require_api_key)])
async def get_root_status(root_id: str):
    """Get per-root scheduler state (watermarks, failures, next run)."""
    from watched_folders import get_folder_by_root_id
    folder = get_folder_by_root_id(root_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Root not found: {root_id}",
        )
    return {
        "root_id": folder["root_id"],
        "folder_path": folder["folder_path"],
        "execution_scope": folder.get("execution_scope"),
        "enabled": folder.get("enabled"),
        "paused": folder.get("paused"),
        "schedule_cron": folder.get("schedule_cron"),
        "last_scan_started_at": folder.get("last_scan_started_at"),
        "last_scan_completed_at": folder.get("last_scan_completed_at"),
        "last_successful_scan_at": folder.get("last_successful_scan_at"),
        "last_error_at": folder.get("last_error_at"),
        "consecutive_failures": folder.get("consecutive_failures", 0),
        "max_concurrency": folder.get("max_concurrency", 1),
    }


@scheduling_router.post("/scheduler/roots/{root_id}/pause", tags=["Scheduler Admin"], dependencies=[Depends(require_api_key)])
async def pause_root(root_id: str):
    """Pause a server-scope root (skip during scheduled scans)."""
    from watched_folders import get_folder_by_root_id, update_folder
    folder = get_folder_by_root_id(root_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Root not found: {root_id}",
        )
    result = update_folder(folder["id"], paused=True)
    return {"ok": True, "folder": result}


@scheduling_router.post("/scheduler/roots/{root_id}/resume", tags=["Scheduler Admin"], dependencies=[Depends(require_api_key)])
async def resume_root(root_id: str):
    """Resume a paused server-scope root."""
    from watched_folders import get_folder_by_root_id, update_folder, update_scan_watermarks
    folder = get_folder_by_root_id(root_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Root not found: {root_id}",
        )
    # Reset failure streak on resume
    update_scan_watermarks(folder["id"], reset_failures=True)
    result = update_folder(folder["id"], paused=False)
    return {"ok": True, "folder": result}


@scheduling_router.post("/scheduler/roots/{root_id}/scan-now", tags=["Scheduler Admin"], dependencies=[Depends(require_api_key)])
async def scan_root_now(root_id: str):
    """Trigger an immediate scan of a server-scope root."""
    from server_scheduler import get_server_scheduler
    scheduler = get_server_scheduler()
    result = await scheduler.scan_root_now(root_id)
    if not result["ok"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )
    return result["scan_result"]
