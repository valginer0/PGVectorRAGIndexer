"""
System, Health, and Version information routes for PGVectorRAGIndexer.
"""

import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from version import __version__
from api_models import (
    API_VERSION, MIN_CLIENT_VERSION, MAX_CLIENT_VERSION,
    HealthResponse, StatsResponse, APIErrorResponse
)
from services import get_indexer, init_complete, init_error
from database import get_db_manager
from embeddings import get_embedding_service
from auth import require_api_key
from license import get_current_license

logger = logging.getLogger(__name__)

# Router for unversioned app-level routes
system_app_router = APIRouter(tags=["General"])

# Router for versioned v1 routes
system_v1_router = APIRouter(tags=["General"])


@system_app_router.get("/api")
async def api_info():
    """API information endpoint."""
    license_info = get_current_license()
    info = {
        "name": "PGVectorRAGIndexer API",
        "version": __version__,
        "api_version": API_VERSION,
        "description": "Semantic document search using PostgreSQL and pgvector",
        "edition": license_info.edition.value,
        "docs": "/docs",
        "health": "/health",
    }
    # DEMO_MODE check would need to be passed in or imported
    import os
    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        info["demo"] = True
    return info


@system_app_router.get("/api/version")
async def api_version():
    """Get detailed version and compatibility information."""
    info = {
        "server_version": __version__,
        "api_version": API_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "max_client_version": MAX_CLIENT_VERSION,
    }
    import os
    if os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        info["demo"] = True
    return info


@system_app_router.get("/license")
async def license_info():
    """Get current license information."""
    return get_current_license().to_dict()


@system_app_router.get("/health", response_model=HealthResponse, responses={503: {"model": APIErrorResponse}})
async def health_check():
    """Check API and database health."""
    from services import init_complete, init_error # Re-import to ensure latest value
    
    if not init_complete:
        from errors import raise_api_error, ErrorCode
        if init_error:
            raise_api_error(
                ErrorCode.SERVICE_INITIALIZING, 
                message=f"Initialization failed: {init_error}"
            )
        return HealthResponse(
            status="initializing",
            timestamp=datetime.utcnow().isoformat(),
            database={"status": "initializing"},
            embedding_model={"status": "loading"}
        )
    try:
        db_manager = get_db_manager()
        db_health = await asyncio.to_thread(db_manager.health_check)
        
        embedding_service = get_embedding_service()
        model_info = embedding_service.get_model_info()
        
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            database=db_health,
            embedding_model=model_info
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unhealthy: {str(e)}"
        )


@system_v1_router.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_api_key)])
async def get_statistics():
    """Get system statistics."""
    try:
        idx = get_indexer()
        stats = idx.get_statistics()
        
        return StatsResponse(
            total_documents=stats['database']['total_documents'],
            total_chunks=stats['database']['total_chunks'],
            avg_chunks_per_document=stats['database']['avg_chunks_per_document'],
            database_size=stats['database']['database_size'],
            embedding_model=stats['embedding_model']['model_name'],
            embedding_dimension=stats['embedding_model']['dimension']
        )
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(e)}"
        )
