"""
Indexing run monitoring and health routes for PGVectorRAGIndexer.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from auth import require_api_key

logger = logging.getLogger(__name__)

monitoring_router = APIRouter(tags=["Monitoring & Health"])


@monitoring_router.get("/indexing/runs", dependencies=[Depends(require_api_key)])
async def list_indexing_runs(
    limit: int = Query(default=20, ge=1, le=100, description="Maximum runs to return"),
):
    """Get recent indexing runs, newest first."""
    from indexing_runs import get_recent_runs
    try:
        runs = get_recent_runs(limit=limit)
        return {"runs": runs, "count": len(runs)}
    except Exception as e:
        logger.error(f"Failed to list indexing runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list indexing runs: {str(e)}",
        )


@monitoring_router.get("/indexing/runs/summary", dependencies=[Depends(require_api_key)])
async def indexing_run_summary():
    """Get aggregate statistics about indexing runs."""
    from indexing_runs import get_run_summary
    try:
        return get_run_summary()
    except Exception as e:
        logger.error(f"Failed to get run summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get run summary: {str(e)}",
        )


@monitoring_router.get("/indexing/runs/{run_id}", dependencies=[Depends(require_api_key)])
async def get_indexing_run(run_id: str):
    """Get a single indexing run by ID."""
    from indexing_runs import get_run_by_id
    try:
        run = get_run_by_id(run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Indexing run not found: {run_id}",
            )
        return run
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get indexing run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get indexing run: {str(e)}",
        )
