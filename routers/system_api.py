"""
System, Health, and Version information routes for PGVectorRAGIndexer.
"""

import asyncio
import logging
import os
import time
import sys
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from auth import is_loopback_request

_START_TIME = time.time()

def _get_system_metrics() -> dict:
    """Collect non-blocking system metrics with safe fallbacks."""
    metrics = {
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "cpu_load_1m": None,
        "memory_rss_bytes": None
    }
    
    try:
        import psutil
        process = psutil.Process()
        metrics["memory_rss_bytes"] = process.memory_info().rss
        # Use os.getloadavg() for consistent 1-minute load average semantics
        if hasattr(os, "getloadavg"):
            metrics["cpu_load_1m"] = os.getloadavg()[0]
    except Exception:
        # Fallback to standard library
        try:
            if hasattr(os, "getloadavg"):
                metrics["cpu_load_1m"] = os.getloadavg()[0]
        except Exception:
            pass
            
        try:
            import resource
            # Note: ru_maxrss reports *peak* RSS (not current). This is a best-effort
            # fallback when psutil is unavailable. On Linux it is in KB, on macOS in bytes.
            mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                metrics["memory_rss_bytes"] = mem
            else:
                metrics["memory_rss_bytes"] = mem * 1024
        except Exception:
            pass
            
    return metrics

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


# Also serve at /api/v1/version so the desktop client (which uses api_base)
# can reach it without a 404.
@system_v1_router.get("/version")
async def api_version_v1():
    """Get version info (v1-prefixed alias)."""
    return await api_version()


@system_app_router.get("/license")
async def license_info():
    """Get current license information."""
    return get_current_license().to_dict()


@system_v1_router.post("/license/install", dependencies=[Depends(require_api_key)])
async def install_server_license(request: Request):
    """Persist a backend license token so server-managed endpoints can use it."""
    from license import validate_license_key, resolve_verification_context
    from server_settings_store import set_server_license_key
    from errors import raise_api_error, ErrorCode

    if not is_loopback_request(request):
        raise_api_error(
            ErrorCode.FORBIDDEN,
            message="License install is only allowed from the local machine.",
            details={"loopback_required": True},
        )

    body = await request.json()
    license_key = (body.get("license_key") or "").strip() if isinstance(body, dict) else ""
    if not license_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="license_key is required")

    signing_secret, algorithms = resolve_verification_context()
    validate_license_key(license_key, signing_secret, algorithms)
    set_server_license_key(license_key)
    return {"status": "stored"}


@system_v1_router.post("/license/reload")
async def reload_license():
    """Force the server to reload the license from disk."""
    from license import reset_license, load_license, set_current_license
    reset_license()
    # Force immediate reload
    new_lic = load_license(allow_db_fallback=True)
    set_current_license(new_lic)
    return {"status": "reloaded", "license": new_lic.to_dict()}


@system_app_router.get(
    "/health", 
    response_model=HealthResponse, 
    responses={
        500: {
            "model": APIErrorResponse,
            "description": "Service initialization failed",
            "content": {
                "application/json": {
                    "example": {
                        "error_code": "SYS_1004",
                        "message": "Initialization failed: Database connection refused",
                        "details": {"context": "startup"}
                    }
                }
            }
        },
        503: {"model": APIErrorResponse, "description": "Service unavailable"}
    }
)
async def health_check():
    """Check API and database health."""
    from services import init_complete, init_error, recovery_message # Re-import to ensure latest value
    
    if not init_complete:
        from errors import raise_api_error, ErrorCode
        if init_error:
            raise_api_error(
                ErrorCode.SERVICE_INITIALIZATION_FAILED, 
                message=f"Initialization failed: {init_error}"
            )
        return HealthResponse(
            status="initializing",
            timestamp=datetime.utcnow().isoformat(),
            database={"status": "initializing"},
            embedding_model={"status": "loading"},
            system=_get_system_metrics()
        )
    try:
        db_manager = get_db_manager()
        db_health = await asyncio.to_thread(db_manager.health_check)
        
        embedding_service = get_embedding_service()
        model_info = embedding_service.get_model_info()
        
        response = HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            database=db_health,
            embedding_model=model_info,
            system=_get_system_metrics(),
        )
        if recovery_message:
            response.recovery_message = recovery_message
        return response
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
