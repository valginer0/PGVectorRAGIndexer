"""
Virtual Root and Path Mapping management routes for PGVectorRAGIndexer.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from auth import require_api_key

logger = logging.getLogger(__name__)

path_mapping_router = APIRouter(tags=["Path Mapping"])


@path_mapping_router.get("/virtual-roots", dependencies=[Depends(require_api_key)])
async def list_virtual_roots(client_id: Optional[str] = Query(default=None)):
    """List virtual roots, optionally filtered by client_id."""
    from virtual_roots import list_roots
    try:
        roots = list_roots(client_id=client_id)
        return {"roots": roots, "count": len(roots)}
    except Exception as e:
        logger.error(f"Failed to list virtual roots: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list virtual roots: {str(e)}",
        )


@path_mapping_router.get("/virtual-roots/names", dependencies=[Depends(require_api_key)])
async def list_virtual_root_names():
    """List distinct virtual root names across all clients."""
    from virtual_roots import list_root_names
    try:
        names = list_root_names()
        return {"names": names, "count": len(names)}
    except Exception as e:
        logger.error(f"Failed to list virtual root names: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list virtual root names: {str(e)}",
        )


@path_mapping_router.get("/virtual-roots/{name}/mappings", dependencies=[Depends(require_api_key)])
async def get_virtual_root_mappings(name: str):
    """Get all client mappings for a given virtual root name."""
    from virtual_roots import get_mappings_for_root
    try:
        mappings = get_mappings_for_root(name)
        return {"name": name, "mappings": mappings, "count": len(mappings)}
    except Exception as e:
        logger.error(f"Failed to get mappings for root {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get mappings: {str(e)}",
        )


@path_mapping_router.post("/virtual-roots", dependencies=[Depends(require_api_key)])
async def add_virtual_root(request: Request):
    """Add or update a virtual root mapping."""
    from virtual_roots import add_root
    try:
        body = await request.json()
        name = body.get("name")
        client_id = body.get("client_id")
        local_path = body.get("local_path")
        if not name or not client_id or not local_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name, client_id, and local_path are required",
            )
        result = add_root(name=name, client_id=client_id, local_path=local_path)
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add virtual root",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add virtual root: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add virtual root: {str(e)}",
        )


@path_mapping_router.delete("/virtual-roots/{root_id}", dependencies=[Depends(require_api_key)])
async def delete_virtual_root(root_id: str):
    """Remove a virtual root by ID."""
    from virtual_roots import remove_root
    try:
        if remove_root(root_id):
            return {"ok": True}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Virtual root not found: {root_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove virtual root: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove virtual root: {str(e)}",
        )


@path_mapping_router.post("/virtual-roots/resolve", dependencies=[Depends(require_api_key)])
async def resolve_virtual_path(request: Request):
    """Resolve a virtual path to a local path for a given client."""
    from virtual_roots import resolve_path
    try:
        body = await request.json()
        virtual_path = body.get("virtual_path")
        client_id = body.get("client_id")
        if not virtual_path or not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="virtual_path and client_id are required",
            )
        local_path = resolve_path(virtual_path, client_id)
        if local_path is not None:
            return {"virtual_path": virtual_path, "local_path": local_path}
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No mapping found for root in: {virtual_path}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve path: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve path: {str(e)}",
        )
