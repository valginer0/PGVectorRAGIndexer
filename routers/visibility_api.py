"""
Document Visibility and Ownership management routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from auth import require_api_key, require_admin

logger = logging.getLogger(__name__)

visibility_router = APIRouter(tags=["Document Visibility"])


@visibility_router.get("/documents/{document_id}/visibility", dependencies=[Depends(require_api_key)])
async def get_document_visibility_endpoint(document_id: str):
    """Get visibility info for a document."""
    from document_visibility import get_document_visibility
    try:
        info = get_document_visibility(document_id)
        if not info:
            raise HTTPException(status_code=404, detail="Document not found")
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document visibility: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document visibility: {str(e)}",
        )


@visibility_router.put("/documents/{document_id}/visibility", dependencies=[Depends(require_api_key)])
async def set_document_visibility_endpoint(document_id: str, request: Request):
    """Set visibility for a document."""
    from document_visibility import (
        set_document_visibility,
        set_document_owner_and_visibility, 
        set_document_owner,
    )
    try:
        body = await request.json()
        visibility = body.get("visibility")
        owner_id = body.get("owner_id")

        if visibility and owner_id:
            updated = set_document_owner_and_visibility(document_id, owner_id, visibility)
        elif visibility:
            updated = set_document_visibility(document_id, visibility)
        elif owner_id:
            updated = set_document_owner(document_id, owner_id)
        else:
            raise HTTPException(status_code=400, detail="Provide 'visibility' and/or 'owner_id'")

        if updated == -1:
            raise HTTPException(status_code=400, detail="Invalid visibility value. Use 'shared' or 'private'.")
        if updated == 0:
            raise HTTPException(status_code=404, detail="Document not found")

        from activity_log import log_activity
        log_activity(
            "document.visibility_changed",
            details={"document_id": document_id, "visibility": visibility, "owner_id": owner_id},
        )
        return {"ok": True, "document_id": document_id, "chunks_updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set document visibility: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set document visibility: {str(e)}",
        )


@visibility_router.post("/documents/{document_id}/transfer", dependencies=[Depends(require_admin)])
async def transfer_document_ownership_endpoint(document_id: str, request: Request):
    """Transfer document ownership to another user (admin only)."""
    from document_visibility import transfer_ownership
    try:
        body = await request.json()
        new_owner_id = body.get("new_owner_id")
        if not new_owner_id:
            raise HTTPException(status_code=400, detail="'new_owner_id' is required")

        updated = transfer_ownership(document_id, new_owner_id)
        if updated == 0:
            raise HTTPException(status_code=404, detail="Document not found")

        from activity_log import log_activity
        log_activity(
            "document.ownership_transferred",
            details={"document_id": document_id, "new_owner_id": new_owner_id},
        )
        return {"ok": True, "document_id": document_id, "chunks_updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to transfer ownership: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to transfer ownership: {str(e)}",
        )


@visibility_router.get("/users/{user_id}/documents", dependencies=[Depends(require_api_key)])
async def list_user_documents_endpoint(
    user_id: str,
    visibility: Optional[str] = Query(default=None, description="Filter: 'shared' or 'private'"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List documents owned by a specific user."""
    from document_visibility import list_user_documents
    try:
        docs = list_user_documents(user_id, visibility=visibility, limit=limit, offset=offset)
        return {"documents": docs, "count": len(docs)}
    except Exception as e:
        logger.error(f"Failed to list user documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list user documents: {str(e)}",
        )


@visibility_router.post("/documents/bulk-visibility", dependencies=[Depends(require_admin)])
async def bulk_set_visibility_endpoint(request: Request):
    """Set visibility for multiple documents at once (admin only)."""
    from document_visibility import bulk_set_visibility
    try:
        body = await request.json()
        document_ids = body.get("document_ids", [])
        visibility = body.get("visibility")
        if not document_ids or not visibility:
            raise HTTPException(status_code=400, detail="'document_ids' and 'visibility' are required")

        updated = bulk_set_visibility(document_ids, visibility)
        if updated == -1:
            raise HTTPException(status_code=400, detail="Invalid visibility value. Use 'shared' or 'private'.")

        from activity_log import log_activity
        log_activity(
            "document.bulk_visibility_changed",
            details={"document_ids": document_ids, "visibility": visibility, "chunks_updated": updated},
        )
        return {"ok": True, "chunks_updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bulk set visibility: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk set visibility: {str(e)}",
        )
