"""
FastAPI REST API orchestrator for PGVectorRAGIndexer.

Main entry point that assembles modular routers and provides the core app instance.
Functional logic is delegated to the `routers/` package.
"""

import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile, File, Form, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from api_models import (
    IndexRequest, IndexResponse, SearchRequest, SearchResultModel, 
    SearchResponse, DocumentInfo, DocumentListResponse, HealthResponse, 
    StatsResponse, BulkDeleteRequest, BulkDeletePreview, BulkDeleteResponse, 
    ExportRequest, RestoreRequest, RetentionRunRequest,
    API_VERSION, MIN_CLIENT_VERSION, MAX_CLIENT_VERSION
)

from config import get_config
from database import get_db_manager, close_db_manager, DocumentRepository
from embeddings import get_embedding_service
from document_processor import DocumentProcessor, UnsupportedFormatError, DocumentProcessingError, EncryptedPDFError
from indexer_v2 import DocumentIndexer
from retriever_v2 import DocumentRetriever, SearchResult
from auth import require_api_key, require_admin, require_permission

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


from services import (
    get_indexer, get_retriever, init_complete, init_error, 
    encrypted_pdfs_encountered, _add_deprecation_headers
)


def _run_startup():
    """Run the heavy startup tasks (migrations, services)."""
    import sys
    import services
    try:
        logger.info("[init] Running database migrations...")
        sys.stdout.flush()
        # Run database migrations before initializing services
        from migrate import run_migrations
        if not run_migrations():
            logger.warning(
                "Database migration failed — the app may not work correctly. "
                "Check database connection and logs."
            )
        logger.info("[init] Migrations complete")
        sys.stdout.flush()

        # Load and validate license key
        from license import load_license, set_current_license
        license_info = load_license()
        set_current_license(license_info)
        logger.info("Edition: %s", license_info.edition.value.title())
        if license_info.warning:
            logger.warning("License warning: %s", license_info.warning)

        # Security check: warn if binding to all interfaces without auth
        if config.api.host in ("0.0.0.0", "::") and not config.api.require_auth:
            logger.warning(
                "⚠️  SECURITY WARNING: Server is binding to %s (all interfaces) "
                "with authentication DISABLED. Any host on the network can access "
                "this API. Set API_REQUIRE_AUTH=true or API_HOST=127.0.0.1.",
                config.api.host,
            )

        # Initialize services
        logger.info("[init] Initializing database manager...")
        sys.stdout.flush()
        _ = get_db_manager()
        logger.info("[init] Database manager ready. Loading embedding model...")
        sys.stdout.flush()
        _ = get_embedding_service()
        logger.info("[init] Services initialized successfully")
        sys.stdout.flush()
        services.init_complete = True
    except Exception as e:
        logger.error(f"[init] Failed to initialize services: {e}", exc_info=True)
        sys.stdout.flush()
        services.init_error = str(e)


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    import services
    # Startup
    logger.info("Starting PGVectorRAGIndexer API...")

    import threading
    def deferred_startup():
        _run_startup()

    init_thread = threading.Thread(target=deferred_startup, daemon=True)
    init_thread.start()
    
    demo_mode = os.environ.get("DEMO_MODE", "").strip() == "1"
    if demo_mode:
        logger.info("Demo mode: deferred initialization to background thread")
    else:
        logger.info("Deferred initialization to background thread (preventing lifespan block)")

    # Start server scheduler if enabled (#6b)
    _server_scheduler = None
    try:
        from server_scheduler import ServerScheduler, get_server_scheduler
        if ServerScheduler.is_enabled():
            _server_scheduler = get_server_scheduler()
            await _server_scheduler.start()
            logger.info("Server scheduler enabled and started")
    except Exception as e:
        logger.warning("Failed to start server scheduler: %s", e)

    # Start retention maintenance runner (independent of server scheduler)
    _retention_runner = None
    try:
        from retention_maintenance import (
            RetentionMaintenanceRunner,
            get_retention_maintenance_runner,
        )

        if RetentionMaintenanceRunner.is_enabled():
            _retention_runner = get_retention_maintenance_runner()
            await _retention_runner.start()
            logger.info("Retention maintenance runner started")
    except Exception as e:
        logger.warning("Failed to start retention maintenance runner: %s", e)

    yield
    
    # Shutdown
    logger.info("Shutting down PGVectorRAGIndexer API...")
    if _server_scheduler:
        await _server_scheduler.stop()
    if _retention_runner:
        await _retention_runner.stop()
    close_db_manager()
    logger.info("Cleanup complete")


# Import version from central module
from version import __version__


# Create FastAPI app
config = get_config()
app = FastAPI(
    title="PGVectorRAGIndexer API",
    description="REST API for semantic document search using PostgreSQL and pgvector",
    version=__version__,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add TrustedHost middleware (restrict allowed Host headers)
if config.api.allowed_hosts != ["*"]:
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=config.api.allowed_hosts,
    )

# ---------------------------------------------------------------------------
# Demo / Read-Only Mode (#15)
# ---------------------------------------------------------------------------
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

# Paths that are allowed even in demo mode (reads + search)
_DEMO_ALLOWED_POST_PATHS = {
    "/search",
    "/api/v1/search",
    "/virtual-roots/resolve",
    "/api/v1/virtual-roots/resolve",
}

if DEMO_MODE:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse as StarletteJSONResponse

    class DemoModeMiddleware(BaseHTTPMiddleware):
        """Block write operations in demo mode."""
        async def dispatch(self, request, call_next):
            method = request.method.upper()
            path = request.url.path.rstrip("/")

            # Allow all GET/HEAD/OPTIONS
            if method in ("GET", "HEAD", "OPTIONS"):
                return await call_next(request)

            # Allow whitelisted POST paths (search, resolve)
            if method == "POST" and path in _DEMO_ALLOWED_POST_PATHS:
                return await call_next(request)

            # Block all other writes
            return StarletteJSONResponse(
                status_code=403,
                content={
                    "detail": "This is a read-only demo instance. "
                    "Install PGVectorRAG locally to index your own documents.",
                    "demo": True,
                },
            )

    app.add_middleware(DemoModeMiddleware)
    logger.info("DEMO_MODE enabled — write operations are blocked")

# Mount static files for web UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ---------------------------------------------------------------------------
# Versioned API Router — all data endpoints live here
# ---------------------------------------------------------------------------
v1_router = APIRouter(tags=["v1"])

# Modular Routers
from routers.system_api import system_app_router, system_v1_router
from routers.maintenance_api import maintenance_router
from routers.indexing_api import indexing_router
from routers.search_api import search_router
from routers.identity_api import identity_router
from routers.scheduling_api import scheduling_router
from routers.monitoring_api import monitoring_router
from routers.path_mapping_api import path_mapping_router
from routers.visibility_api import visibility_router
from routers.scim_api import scim_router

app.include_router(system_app_router)
v1_router.include_router(system_v1_router)
v1_router.include_router(maintenance_router)
v1_router.include_router(indexing_router)
v1_router.include_router(search_router)
v1_router.include_router(identity_router)
v1_router.include_router(scheduling_router)
v1_router.include_router(monitoring_router)
v1_router.include_router(path_mapping_router)
v1_router.include_router(visibility_router)

# Legacy functional re-exports for backward compatibility (internal imports and tests)
from routers.maintenance_api import (
    apply_activity_retention,
    purge_quarantine,
    get_retention_policy,
    run_retention_policy,
    get_retention_status
)
from routers.identity_api import (
    list_roles_endpoint,
    get_role_endpoint,
    list_permissions_endpoint,
    check_role_permission_endpoint,
    create_role_endpoint,
    update_role_endpoint,
    delete_role_endpoint
)
from routers.search_api import (
    get_metadata_keys,
    get_metadata_values,
    bulk_delete_documents,
    export_documents,
    restore_documents
)

# Mount SCIM router at /scim/v2
app.include_router(scim_router, prefix="/scim/v2")


# API Endpoints

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve the web UI."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            return f.read()
    return "<h1>PGVectorRAGIndexer API</h1><p>Visit <a href='/docs'>/docs</a> for API documentation</p>"






# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# API Finalization
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Mount versioned router at /api/v1 (canonical) and / (backward compat)
# ---------------------------------------------------------------------------
app.include_router(v1_router, prefix="/api/v1")
app.include_router(v1_router)  # backward compat: old unversioned paths


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle FastAPI/Starlette HTTPExceptions by flattening structured details."""
    detail = exc.detail
    error_code = "GENERIC_HTTP_ERROR"
    message = str(detail)
    details = None
    
    if isinstance(detail, dict):
        error_code = detail.get("error_code", error_code)
        message = detail.get("message", message)
        details = detail.get("details")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": error_code,
            "message": message,
            "details": details
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all for truly unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    from errors import ErrorCode
    
    # Map to centralized Internal Server Error
    err = ErrorCode.INTERNAL_SERVER_ERROR
    return JSONResponse(
        status_code=err.status_code,
        content={
            "error_code": err.code,
            "message": err.message,
            "details": {"exception": str(exc)}
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "api:app",
        host=config.api.host,
        port=config.api.port,
        reload=config.api.reload,
        log_level=config.api.log_level
    )
