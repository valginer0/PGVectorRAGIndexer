"""
Document Visibility and Ownership management routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from auth import require_api_key, require_admin, require_permission, is_auth_required

logger = logging.getLogger(__name__)

visibility_router = APIRouter(tags=["Document Visibility"])


@visibility_router.get("/documents/{document_id}/visibility")
async def get_document_visibility_endpoint(
    document_id: str,
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get visibility info for a visible document. Hidden documents return 404."""
    from document_visibility import get_document_visibility, document_visible_for_key_record
    try:
        info = get_document_visibility(document_id)
        if not info or not document_visible_for_key_record(document_id, key_record):
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


def _may_change_visibility(key_record, document_id: str) -> bool:
    """Ownership check for visibility changes.

    - Local mode / bootstrap (no key context): allowed.
    - documents.visibility.all (admins, sre): any document.
    - documents.visibility: only documents the caller owns. Unowned
      documents require .all — flipping someone else's (or nobody's) doc
      must not be possible, or a private doc could be flipped to shared
      and read via search.
    """
    if not isinstance(key_record, dict):
        return True
    from users import get_user_by_api_key, count_admins
    from role_permissions import has_permission
    from document_visibility import get_document_visibility

    user = get_user_by_api_key(key_record["id"])
    if user is None:
        # Unlinked key: allow only during bootstrap (no admins exist yet)
        return count_admins() == 0
    role = user.get("role", "")
    if has_permission(role, "documents.visibility.all"):
        return True
    info = get_document_visibility(document_id) or {}
    return info.get("owner_id") == user["id"]


@visibility_router.put("/documents/{document_id}/visibility")
async def set_document_visibility_endpoint(
    document_id: str,
    request: Request,
    key_record: Optional[dict] = Depends(require_permission("documents.visibility")),
):
    """Set visibility for a document.

    Requires the ``documents.visibility`` permission, and callers without
    ``documents.visibility.all`` may only change documents they own.
    Changing ``owner_id`` requires admin privileges — use
    ``POST /documents/{id}/transfer`` instead.
    """
    from document_visibility import (
        set_document_visibility,
        set_document_owner_and_visibility,
        set_document_owner,
    )
    try:
        if not _may_change_visibility(key_record, document_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only change visibility of documents you own "
                       "(documents.visibility.all required for others' documents).",
            )
        body = await request.json()
        visibility = body.get("visibility")
        owner_id = body.get("owner_id")

        if owner_id and is_auth_required(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Changing owner_id requires admin privileges. Use POST /documents/{id}/transfer.",
            )

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


@visibility_router.get("/users/{user_id}/documents")
async def list_user_documents_endpoint(
    user_id: str,
    visibility: Optional[str] = Query(default=None, description="Filter: 'shared' or 'private'"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """List documents owned by a user.

    Local mode may list any user. In team mode, only admins can list another
    user's documents; regular users can list their own documents only.
    """
    from document_visibility import (
        is_admin_key_record,
        list_user_documents,
        resolve_user_id_for_key_record,
    )
    try:
        if isinstance(key_record, dict):
            caller_user_id = resolve_user_id_for_key_record(key_record)
            if not is_admin_key_record(key_record) and caller_user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only list your own documents.",
                )
        docs = list_user_documents(user_id, visibility=visibility, limit=limit, offset=offset)
        return {"documents": docs, "count": len(docs)}
    except HTTPException:
        raise
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


# ---------------------------------------------------------------------------
# Role collection grants (document-set access control)
# ---------------------------------------------------------------------------


@visibility_router.get("/roles/collections", dependencies=[Depends(require_admin)])
async def list_collection_grants_endpoint(role: Optional[str] = Query(default=None)):
    """List role→collection grants (admin only). Optionally filter by role."""
    from collection_grants import list_grants
    try:
        grants = list_grants(role=role)
        return {"grants": grants, "count": len(grants)}
    except Exception as e:
        logger.error(f"Failed to list collection grants: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list collection grants: {str(e)}",
        )


@visibility_router.put("/roles/{role}/collections/{namespace}", dependencies=[Depends(require_admin)])
async def grant_collection_endpoint(role: str, namespace: str):
    """Grant a role read access to a collection/namespace (admin only).

    Use namespace '*' to make a listed role unrestricted. A role with no
    grants at all is unrestricted (grants are opt-in per role).
    """
    from collection_grants import grant_collection
    try:
        if not grant_collection(role, namespace):
            raise HTTPException(status_code=404, detail=f"Unknown role: {role}")
        from activity_log import log_activity
        log_activity(
            "role.collection_granted",
            details={"role": role, "namespace": namespace},
        )
        return {"ok": True, "role": role, "namespace": namespace}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to grant collection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to grant collection: {str(e)}",
        )


@visibility_router.delete("/roles/{role}/collections/{namespace}", dependencies=[Depends(require_admin)])
async def revoke_collection_endpoint(role: str, namespace: str):
    """Revoke a role's access to a collection/namespace (admin only)."""
    from collection_grants import revoke_collection
    try:
        deleted = revoke_collection(role, namespace)
        if not deleted:
            raise HTTPException(status_code=404, detail="Grant not found")
        from activity_log import log_activity
        log_activity(
            "role.collection_revoked",
            details={"role": role, "namespace": namespace},
        )
        return {"ok": True, "role": role, "namespace": namespace}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke collection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke collection: {str(e)}",
        )
