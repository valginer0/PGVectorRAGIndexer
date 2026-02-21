"""
Maintenance, Retention, Quarantine, and Compliance routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query

from api_models import RetentionRunRequest
from services import _add_deprecation_headers
from auth import require_api_key, require_admin
from database import get_db_manager

logger = logging.getLogger(__name__)

maintenance_router = APIRouter(tags=["Maintenance & Activity"])


@maintenance_router.get("/activity", tags=["Activity Log"], dependencies=[Depends(require_api_key)])
async def get_activity_log(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    client_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
):
    """Query recent activity log entries."""
    from activity_log import get_recent, get_activity_count
    try:
        entries = get_recent(limit=limit, offset=offset, client_id=client_id, action=action)
        total = get_activity_count(client_id=client_id, action=action)
        return {"entries": entries, "count": len(entries), "total": total}
    except Exception as e:
        logger.error(f"Failed to query activity log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query activity log: {str(e)}",
        )


@maintenance_router.post("/activity", tags=["Activity Log"], dependencies=[Depends(require_api_key)])
async def post_activity(request: Request):
    """Record an activity log entry."""
    from activity_log import log_activity
    try:
        body = await request.json()
        action_type = body.get("action")
        if not action_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="action is required",
            )
        entry_id = log_activity(
            action=action_type,
            client_id=body.get("client_id"),
            user_id=body.get("user_id"),
            details=body.get("details"),
        )
        if entry_id:
            return {"id": entry_id, "ok": True}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to log activity",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to log activity: {str(e)}",
        )


@maintenance_router.get("/activity/actions", tags=["Activity Log"], dependencies=[Depends(require_api_key)])
async def get_activity_action_types():
    """Get distinct action types in the activity log."""
    from activity_log import get_action_types
    try:
        types = get_action_types()
        return {"actions": types, "count": len(types)}
    except Exception as e:
        logger.error(f"Failed to get action types: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get action types: {str(e)}",
        )


@maintenance_router.get("/activity/export", tags=["Activity Log"], dependencies=[Depends(require_api_key)])
async def export_activity_csv(
    client_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=10000, ge=1, le=100000),
):
    """Export activity log as CSV."""
    from activity_log import export_csv
    try:
        csv_data = export_csv(client_id=client_id, action=action, limit=limit)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=activity_log.csv"},
        )
    except Exception as e:
        logger.error(f"Failed to export activity log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export: {str(e)}",
        )


@maintenance_router.post("/activity/retention", tags=["Activity Log"], dependencies=[Depends(require_api_key)],
                         deprecated=True)
async def apply_activity_retention(request: Request, response: Response):
    """Apply retention policy — delete entries older than N days.

    .. deprecated:: 2.4.5
        Use ``POST /retention/run`` instead. This endpoint will be removed after 2026-11-01.
    """
    _add_deprecation_headers(response)
    from retention_policy import apply_retention as apply_retention_policy
    try:
        body = await request.json()
        days = body.get("days")
        if not days or not isinstance(days, int) or days < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="days must be a positive integer",
            )
        result = apply_retention_policy(
            activity_days=days,
            cleanup_saml_sessions=False,
        )
        deleted = result.get("activity_deleted", 0)
        return {"deleted": deleted, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply retention: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply retention: {str(e)}",
        )


@maintenance_router.get("/retention/policy", tags=["Retention"], dependencies=[Depends(require_api_key)])
async def get_retention_policy():
    """Return effective per-category retention defaults."""
    from retention_policy import get_policy_defaults
    return {"policy": get_policy_defaults()}


@maintenance_router.post("/retention/run", tags=["Retention"], dependencies=[Depends(require_api_key)])
async def run_retention_policy(request: RetentionRunRequest):
    """Run retention orchestration once with optional per-category overrides."""
    from retention_policy import apply_retention

    result = apply_retention(
        activity_days=request.activity_days,
        quarantine_days=request.quarantine_days,
        indexing_runs_days=request.indexing_runs_days,
        cleanup_saml_sessions=request.cleanup_saml_sessions,
    )
    if not result.get("ok", False):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Retention run failed"),
        )
    return result


@maintenance_router.get("/retention/status", tags=["Retention"], dependencies=[Depends(require_api_key)])
async def get_retention_status():
    """Get retention maintenance runner status."""
    from retention_maintenance import get_retention_maintenance_runner
    runner = get_retention_maintenance_runner()
    return runner.get_status()


@maintenance_router.get("/compliance/export", tags=["Compliance"], dependencies=[Depends(require_admin)])
async def compliance_export():
    """Export compliance report as ZIP (admin-only)."""
    from compliance_export import export_compliance_report
    try:
        data = export_compliance_report()
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=compliance_report.zip"},
        )
    except Exception as e:
        logger.error(f"Compliance export failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compliance export failed: {str(e)}",
        )


@maintenance_router.get("/quarantine", tags=["Quarantine"], dependencies=[Depends(require_api_key)])
async def list_quarantined_docs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List quarantined documents with pagination."""
    from quarantine import list_quarantined
    items = list_quarantined(limit=limit, offset=offset)
    return {"quarantined": items, "count": len(items)}


@maintenance_router.post("/quarantine/{source_uri:path}/restore", tags=["Quarantine"], dependencies=[Depends(require_api_key)])
async def restore_quarantined(source_uri: str):
    """Remove quarantine status from a document's chunks."""
    from quarantine import restore_chunks
    count = restore_chunks(source_uri)
    if count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quarantined chunks found for: {source_uri}",
        )
    return {"restored": count, "source_uri": source_uri}


@maintenance_router.post("/quarantine/purge", tags=["Quarantine"], dependencies=[Depends(require_api_key)],
                         deprecated=True)
async def purge_quarantine(response: Response, retention_days: Optional[int] = Query(default=None)):
    """Permanently delete chunks quarantined longer than the retention window.

    .. deprecated:: 2.4.5
        Use ``POST /retention/run`` instead. This endpoint will be removed after 2026-11-01.
    """
    _add_deprecation_headers(response)
    from retention_policy import apply_retention
    result = apply_retention(quarantine_days=retention_days, cleanup_saml_sessions=False)
    count = result.get("quarantine_purged", 0)
    return {"purged": count}


@maintenance_router.get("/quarantine/stats", tags=["Quarantine"], dependencies=[Depends(require_api_key)])
async def quarantine_stats():
    """Get quarantine summary statistics."""
    from quarantine import get_quarantine_stats
    return get_quarantine_stats()
