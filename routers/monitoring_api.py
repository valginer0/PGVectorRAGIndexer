"""
Indexing run monitoring and health routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from auth import require_api_key

logger = logging.getLogger(__name__)

monitoring_router = APIRouter(tags=["Monitoring & Health"])


@monitoring_router.get("/indexing/runs")
async def list_indexing_runs(
    limit: int = Query(default=20, ge=1, le=100, description="Maximum runs to return"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get recent indexing runs, newest first.

    Runs whose source path maps to a document hidden from the caller are omitted.
    """
    from indexing_runs import get_recent_runs
    from document_visibility import filter_entries_by_hidden_source
    try:
        runs = filter_entries_by_hidden_source(get_recent_runs(limit=limit), key_record)
        return {"runs": runs, "count": len(runs)}
    except Exception as e:
        logger.error(f"Failed to list indexing runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list indexing runs: {str(e)}",
        )


@monitoring_router.get("/indexing/runs/summary", dependencies=[Depends(require_api_key)])
async def indexing_run_summary():
    """Get aggregate statistics about indexing runs (counts only, no paths)."""
    from indexing_runs import get_run_summary
    try:
        return get_run_summary()
    except Exception as e:
        logger.error(f"Failed to get run summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get run summary: {str(e)}",
        )


@monitoring_router.get("/indexing/runs/{run_id}")
async def get_indexing_run(
    run_id: str,
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get a single indexing run by ID. Runs for hidden documents return 404."""
    from indexing_runs import get_run_by_id
    from document_visibility import filter_entries_by_hidden_source
    try:
        run = get_run_by_id(run_id)
        if run and not filter_entries_by_hidden_source([run], key_record):
            run = None
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
