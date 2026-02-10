"""
FastAPI REST API for PGVectorRAGIndexer.

Provides HTTP endpoints for indexing, searching, and managing documents.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile, File, Form, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_config
from database import get_db_manager, close_db_manager, DocumentRepository
from embeddings import get_embedding_service
from document_processor import DocumentProcessor, UnsupportedFormatError, DocumentProcessingError, EncryptedPDFError
from indexer_v2 import DocumentIndexer
from retriever_v2 import DocumentRetriever, SearchResult
from auth import require_api_key

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pydantic models for API requests/responses
class IndexRequest(BaseModel):
    """Request model for indexing a document."""
    source_uri: str = Field(..., description="Path or URL to document")
    force_reindex: bool = Field(default=False, description="Force reindex if exists")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Custom metadata")


class IndexResponse(BaseModel):
    """Response model for indexing operation."""
    status: str
    document_id: Optional[str] = None
    source_uri: Optional[str] = None
    chunks_indexed: Optional[int] = None
    message: Optional[str] = None
    indexed_at: Optional[str] = None


class SearchRequest(BaseModel):
    """Request model for search."""
    query: str = Field(..., description="Search query text")
    top_k: Optional[int] = Field(default=None, description="Number of results")
    min_score: Optional[float] = Field(default=None, description="Minimum relevance score")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Search filters")
    use_hybrid: bool = Field(default=False, description="Use hybrid search")
    alpha: Optional[float] = Field(default=None, description="Hybrid search weight")


class SearchResultModel(BaseModel):
    """Model for search result."""
    chunk_id: int
    document_id: str
    chunk_index: int
    text_content: str
    source_uri: str
    distance: float
    relevance_score: float
    metadata: Optional[Dict[str, Any]] = None
    document_type: Optional[str] = None


class SearchResponse(BaseModel):
    """Response model for search."""
    query: str
    results: List[SearchResultModel]
    total_results: int
    search_time_ms: float


class DocumentInfo(BaseModel):
    """Model for document information."""
    document_id: str
    source_uri: str
    chunk_count: int
    indexed_at: datetime
    last_updated: Optional[datetime] = None
    document_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentListResponse(BaseModel):
    """Paginated list response for documents."""
    items: List[DocumentInfo]
    total: int
    limit: int
    offset: int
    sort: Dict[str, str]


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    timestamp: str
    database: Dict[str, Any]
    embedding_model: Dict[str, Any]


class StatsResponse(BaseModel):
    """Response model for statistics."""
    total_documents: int
    total_chunks: int
    avg_chunks_per_document: int
    database_size: str
    embedding_model: str
    embedding_dimension: int


class BulkDeleteRequest(BaseModel):
    """Request model for bulk delete operations."""
    filters: Dict[str, Any] = Field(..., description="Filter criteria for deletion")
    preview: bool = Field(default=True, description="If true, only preview without deleting")


class BulkDeletePreview(BaseModel):
    """Response model for bulk delete preview."""
    document_count: int
    sample_documents: List[Dict[str, Any]]
    filters_applied: Dict[str, Any]


class BulkDeleteResponse(BaseModel):
    """Response model for bulk delete operation."""
    status: str
    chunks_deleted: int
    filters_applied: Dict[str, Any]


class ExportRequest(BaseModel):
    """Request model for exporting documents."""
    filters: Dict[str, Any] = Field(..., description="Filter criteria for export")


class RestoreRequest(BaseModel):
    """Request model for restoring documents."""
    backup_data: List[Dict[str, Any]] = Field(..., description="Backup data from export")


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    logger.info("Starting PGVectorRAGIndexer API...")
    try:
        # Run database migrations before initializing services
        from migrate import run_migrations
        if not run_migrations():
            logger.warning(
                "Database migration failed — the app may not work correctly. "
                "Check database connection and logs."
            )

        # Load and validate license key
        from license import load_license, set_current_license
        license_info = load_license()
        set_current_license(license_info)
        logger.info("Edition: %s", license_info.edition.value.title())
        if license_info.warning:
            logger.warning("License warning: %s", license_info.warning)

        # Initialize services
        _ = get_db_manager()
        _ = get_embedding_service()
        logger.info("Services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down PGVectorRAGIndexer API...")
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

# Mount static files for web UI
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ---------------------------------------------------------------------------
# Versioned API Router — all data endpoints live here
# ---------------------------------------------------------------------------
v1_router = APIRouter(tags=["v1"])

# Initialize services (will be created on first request)
indexer: Optional[DocumentIndexer] = None
retriever: Optional[DocumentRetriever] = None

# Track encrypted PDFs encountered (in-memory, cleared on restart)
# Format: [{"source_uri": "...", "detected_at": "...", "filename": "..."}]
encrypted_pdfs_encountered: List[Dict[str, Any]] = []


def get_indexer() -> DocumentIndexer:
    """Get or create indexer instance."""
    global indexer
    if indexer is None:
        indexer = DocumentIndexer()
    return indexer


def get_retriever() -> DocumentRetriever:
    """Get or create retriever instance."""
    global retriever
    if retriever is None:
        retriever = DocumentRetriever()
    return retriever


# API Endpoints

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve the web UI."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            return f.read()
    return "<h1>PGVectorRAGIndexer API</h1><p>Visit <a href='/docs'>/docs</a> for API documentation</p>"


# ---------------------------------------------------------------------------
# API Version Constants
# ---------------------------------------------------------------------------
API_VERSION = "1"                  # Current API version
MIN_CLIENT_VERSION = "2.4.0"       # Oldest desktop client that works with this API
MAX_CLIENT_VERSION = "99.99.99"    # No upper bound yet


@app.get("/api", tags=["General"])
async def api_info():
    """API information endpoint."""
    from license import get_current_license
    license_info = get_current_license()
    return {
        "name": "PGVectorRAGIndexer API",
        "version": __version__,
        "api_version": API_VERSION,
        "description": "Semantic document search using PostgreSQL and pgvector",
        "edition": license_info.edition.value,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/api/version", tags=["General"])
async def api_version():
    """Get detailed version and compatibility information.

    Desktop clients should call this on connect and warn if their
    version falls outside [min_client_version, max_client_version].
    """
    return {
        "server_version": __version__,
        "api_version": API_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "max_client_version": MAX_CLIENT_VERSION,
    }


@app.get("/license", tags=["General"])
async def license_info():
    """Get current license information."""
    from license import get_current_license
    return get_current_license().to_dict()


@app.get("/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    """Check API and database health."""
    try:
        db_manager = get_db_manager()
        db_health = db_manager.health_check()
        
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


@v1_router.get("/stats", response_model=StatsResponse, tags=["General"], dependencies=[Depends(require_api_key)])
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


@v1_router.post("/index", response_model=IndexResponse, tags=["Indexing"], dependencies=[Depends(require_api_key)])
async def index_document(request: IndexRequest):
    """Index a document from URI."""
    from indexing_runs import start_run, complete_run
    run_id = start_run(trigger="api", source_uri=request.source_uri)
    try:
        idx = get_indexer()
        result = idx.index_document(
            source_uri=request.source_uri,
            force_reindex=request.force_reindex,
            custom_metadata=request.metadata
        )
        
        if result['status'] == 'error':
            complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                         errors=[{"source_uri": request.source_uri, "error": result.get('message', '')}])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result['message']
            )
        
        added = 1 if result.get('status') == 'success' else 0
        skipped = 1 if result.get('status') == 'skipped' else 0
        complete_run(run_id, status="success", files_scanned=1,
                     files_added=added, files_skipped=skipped)
        return IndexResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": request.source_uri, "error": str(e)}])
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Indexing failed: {str(e)}"
        )


@v1_router.post("/upload-and-index", response_model=IndexResponse, tags=["Indexing"], dependencies=[Depends(require_api_key)])
async def upload_and_index(
    file: UploadFile = File(...),
    force_reindex: bool = Form(default=False),
    custom_source_uri: Optional[str] = Form(default=None),
    document_type: Optional[str] = Form(default=None),
    ocr_mode: Optional[str] = Form(default=None)
):
    """
    Upload a file and index it immediately.
    
    This endpoint allows you to index files from any location on your system
    without needing to copy them to the documents directory first.
    
    Args:
        file: The file to upload and index
        force_reindex: Force reindex if file already exists
        custom_source_uri: Custom source URI (full path) to preserve
        document_type: Document type/category tag
        ocr_mode: OCR processing mode ('auto', 'skip', 'only')
        
    Returns:
        IndexResponse with indexing results
        
    Example:
        curl -X POST "http://localhost:8000/upload-and-index" \\
          -F "file=@C:\\Users\\YourName\\Documents\\file.pdf" \\
          -F "ocr_mode=auto"
    """
    import tempfile
    import os
    from indexing_runs import start_run, complete_run
    
    source = custom_source_uri or file.filename or "upload"
    run_id = start_run(trigger="upload", source_uri=source)
    temp_path = None
    try:
        # Create temporary file with original extension
        suffix = os.path.splitext(file.filename)[1] if file.filename else '.tmp'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            # Write uploaded content to temp file
            content = await file.read()
            temp_file.write(content)
        
        logger.info(f"Uploaded file: {file.filename} ({len(content)} bytes) -> {temp_path}")
        
        # Determine the source URI to use (custom path or filename)
        display_name = custom_source_uri if custom_source_uri else file.filename
        
        # Process the file using temp path, but with custom source_uri for document_id
        idx = get_indexer()
        
        # Process document from temp file
        metadata = {
            'upload_method': 'http_upload',
            'original_filename': file.filename,
            'temp_path': temp_path
        }
        
        # Add document type if provided
        if document_type:
            metadata['type'] = document_type
        
        processed_doc = idx.processor.process(
            source_uri=temp_path,
            custom_metadata=metadata,
            ocr_mode=ocr_mode  # Pass OCR mode to processor
        )
        
        # Regenerate document_id based on the display name (not temp path)
        import hashlib
        processed_doc.document_id = hashlib.sha256(display_name.encode()).hexdigest()[:16]
        processed_doc.source_uri = display_name
        processed_doc.metadata['source_uri'] = display_name
        processed_doc.metadata['document_id'] = processed_doc.document_id
        if custom_source_uri:
            processed_doc.metadata['custom_source_uri'] = custom_source_uri
        
        # Check if document already exists
        if not force_reindex and idx.repository.document_exists(processed_doc.document_id):
            complete_run(run_id, status="success", files_scanned=1, files_skipped=1)
            return IndexResponse(
                status='skipped',
                document_id=processed_doc.document_id,
                source_uri=processed_doc.source_uri,
                chunks_indexed=0,
                message='Document already indexed (use force_reindex=true to reindex)'
            )
        
        # Delete existing if force reindex
        if force_reindex and idx.repository.document_exists(processed_doc.document_id):
            logger.info(f"Removing existing document: {processed_doc.document_id}")
            idx.repository.delete_document(processed_doc.document_id)
        
        # Generate embeddings
        logger.info(f"Generating embeddings for {len(processed_doc.chunks)} chunks...")
        chunk_texts = processed_doc.get_chunk_texts()
        embeddings = idx.embedding_service.encode_batch(chunk_texts, show_progress=False)
        
        # Prepare chunks for insertion
        chunks_data = []
        for i, (chunk, embedding) in enumerate(zip(processed_doc.chunks, embeddings)):
            chunks_data.append((
                processed_doc.document_id,
                i,
                chunk.page_content,
                processed_doc.source_uri,  # This is now the original filename
                embedding,
                processed_doc.metadata  # Include metadata
            ))
        
        # Insert into database
        logger.info(f"Storing {len(chunks_data)} chunks in database...")
        idx.repository.insert_chunks(chunks_data)
        
        logger.info(f"✓ Successfully indexed document: {processed_doc.document_id}")
        
        complete_run(run_id, status="success", files_scanned=1,
                     files_added=1 if not force_reindex else 0,
                     files_updated=1 if force_reindex else 0)
        return IndexResponse(
            status='success',
            document_id=processed_doc.document_id,
            source_uri=processed_doc.source_uri,
            chunks_indexed=len(chunks_data)
        )
        
    except HTTPException:
        raise
    except EncryptedPDFError as e:
        # Return 403 with specific error type for encrypted PDFs
        source = custom_source_uri or file.filename
        logger.warning(f"Encrypted PDF detected: {source}")
        
        # Record for later querying
        encrypted_pdfs_encountered.append({
            "source_uri": source,
            "filename": file.filename,
            "detected_at": datetime.utcnow().isoformat()
        })
        
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": "encrypted_pdf"}])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_type": "encrypted_pdf",
                "message": str(e),
                "source_uri": source
            }
        )
    except (UnsupportedFormatError, DocumentProcessingError) as e:
        error_message = str(e) if str(e) else ""
        
        # Check if this is an OCR mode "only" skip (not an error, just skipped)
        if error_message.startswith("Skipped:"):
            logger.info(f"File skipped due to OCR mode: {file.filename}")
            # Return success with 0 chunks to indicate skip
            complete_run(run_id, status="success", files_scanned=1, files_skipped=1)
            return IndexResponse(
                status='skipped',
                document_id='',
                source_uri=custom_source_uri if custom_source_uri else (file.filename or ''),
                chunks_indexed=0,
                message=error_message
            )
        
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": error_message}])
        logger.error(f"Upload and index failed: {e}")
        detail_message = error_message
        if (
            file.filename
            and file.filename.lower().endswith(".doc")
            and "convert" not in detail_message.lower()
        ):
            detail_message = (
                "Legacy .doc format is not supported automatically. "
                "Please install LibreOffice/soffice for conversion or convert the document to .docx."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail_message
        )
    except Exception as e:
        complete_run(run_id, status="failed", files_scanned=1, files_failed=1,
                     errors=[{"source_uri": source, "error": str(e)}])
        logger.error(f"Upload and index failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload and index failed: {str(e)}"
        )
    finally:
        # Clean up temporary file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_path}: {e}")


@v1_router.post("/search", response_model=SearchResponse, tags=["Search"], dependencies=[Depends(require_api_key)])
async def search_documents(request: SearchRequest):
    """Search for relevant documents."""
    import time
    
    try:
        ret = get_retriever()
        
        start_time = time.time()
        
        if request.use_hybrid:
            results = ret.search_hybrid(
                query=request.query,
                top_k=request.top_k,
                alpha=request.alpha
            )
        else:
            results = ret.search(
                query=request.query,
                top_k=request.top_k,
                filters=request.filters,
                min_score=request.min_score
            )
        
        search_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Convert SearchResult objects to Pydantic models
        result_models = [
            SearchResultModel(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                chunk_index=r.chunk_index,
                text_content=r.text_content,
                source_uri=r.source_uri,
                distance=r.distance,
                relevance_score=r.relevance_score,
                metadata=r.metadata,
                document_type=r.document_type
            )
            for r in results
        ]
        
        return SearchResponse(
            query=request.query,
            results=result_models,
            total_results=len(result_models),
            search_time_ms=round(search_time, 2)
        )
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@v1_router.get("/documents", response_model=DocumentListResponse, tags=["Documents"], dependencies=[Depends(require_api_key)])
async def list_documents(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum documents to return"),
    offset: int = Query(default=0, ge=0, description="Number of documents to skip"),
    sort_by: str = Query(default="indexed_at", description="Field to sort by"),
    sort_dir: str = Query(default="desc", description="Sort direction: asc or desc")
):
    """List all indexed documents."""
    try:
        idx = get_indexer()
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        normalized_sort_by = sort_by.lower()
        normalized_sort_dir = sort_dir.lower()

        try:
            documents, total = repo.list_documents(
                limit=limit,
                offset=offset,
                sort_by=normalized_sort_by,
                sort_dir=normalized_sort_dir,
                with_total=True
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        items = [
            DocumentInfo(
                document_id=doc['document_id'],
                source_uri=doc['source_uri'],
                chunk_count=doc['chunk_count'],
                indexed_at=doc['indexed_at'],
                last_updated=doc.get('last_updated'),
                document_type=doc.get('document_type'),
                metadata={"type": doc.get('document_type')} if doc.get('document_type') is not None else {}
            )
            for doc in documents
        ]

        return DocumentListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            sort={
                "by": normalized_sort_by,
                "direction": normalized_sort_dir,
            }
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {str(e)}"
        )


@v1_router.get("/documents/encrypted", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def list_encrypted_pdfs(
    since: Optional[str] = Query(default=None, description="Return only PDFs detected after this ISO datetime"),
    clear: bool = Query(default=False, description="Clear the list after returning it")
):
    """
    List encrypted PDFs that were skipped during indexing.
    
    These are password-protected PDFs that could not be indexed.
    The list is stored in-memory and cleared on server restart.
    """
    global encrypted_pdfs_encountered
    
    result = encrypted_pdfs_encountered.copy()
    
    # Filter by 'since' if provided
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            result = [
                item for item in result
                if datetime.fromisoformat(item['detected_at']) > since_dt
            ]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid datetime format: {since}"
            )
    
    # Clear if requested
    if clear:
        encrypted_pdfs_encountered = []
    
    return {
        "count": len(result),
        "encrypted_pdfs": result
    }


@v1_router.get("/documents/{document_id}", response_model=DocumentInfo, tags=["Documents"], dependencies=[Depends(require_api_key)])
async def get_document(document_id: str):
    """Get document information by ID."""
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        
        doc = repo.get_document_by_id(document_id)
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document not found: {document_id}"
            )
        
        return DocumentInfo(
            document_id=doc['document_id'],
            source_uri=doc['source_uri'],
            chunk_count=doc['chunk_count'],
            indexed_at=doc['indexed_at'],
            last_updated=doc.get('last_updated'),
            document_type=doc.get('document_type'),
            metadata=doc.get('metadata')  # Include metadata with file_hash!
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@v1_router.delete("/documents/{document_id}", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def delete_document(document_id: str):
    """Delete a document by ID."""
    try:
        idx = get_indexer()
        
        if not idx.delete_document(document_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document not found: {document_id}"
            )
        
        return {
            "status": "success",
            "message": f"Document deleted: {document_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


@v1_router.get("/statistics", tags=["General"], dependencies=[Depends(require_api_key)])
async def get_statistics():
    """Get system statistics."""
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        stats = repo.get_statistics()
        
        embedding_service = get_embedding_service()
        model_info = embedding_service.get_model_info()
        
        return {
            "total_documents": stats.get('total_documents', 0),
            "total_chunks": stats.get('total_chunks', 0),
            "database_size_bytes": stats.get('database_size_bytes', 0),
            "embedding_model": model_info.get('model_name', 'unknown')
        }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(e)}"
        )


@v1_router.get("/context", tags=["RAG"], dependencies=[Depends(require_api_key)])
async def get_context(
    query: str = Query(..., description="Search query"),
    top_k: int = Query(default=5, ge=1, le=20, description="Number of chunks"),
    use_hybrid: bool = Query(default=False, description="Use hybrid search")
):
    """Get concatenated context for RAG applications."""
    try:
        ret = get_retriever()
        context = ret.get_context(query, top_k=top_k, use_hybrid=use_hybrid)
        
        return {
            "query": query,
            "context": context,
            "chunks_used": top_k
        }
    except Exception as e:
        logger.error(f"Failed to get context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get context: {str(e)}"
        )


@v1_router.get("/metadata/keys", response_model=List[str], tags=["Metadata"], dependencies=[Depends(require_api_key)])
async def get_metadata_keys(
    pattern: Optional[str] = Query(default=None, description="SQL LIKE pattern to filter keys (e.g., 't%')")
):
    """
    Get all unique metadata keys across all documents.
    
    Useful for discovering what metadata fields are available for filtering.
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        keys = repo.get_metadata_keys(pattern=pattern)
        return keys
    except Exception as e:
        logger.error(f"Failed to get metadata keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metadata keys: {str(e)}"
        )


@v1_router.get("/metadata/values", response_model=List[str], tags=["Metadata"], dependencies=[Depends(require_api_key)])
async def get_metadata_values(
    key: str = Query(..., description="Metadata key to get values for"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum values to return")
):
    """
    Get all unique values for a specific metadata key.
    
    Useful for building filter dropdowns in UI.
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        values = repo.get_metadata_values(key=key, limit=limit)
        return values
    except Exception as e:
        logger.error(f"Failed to get metadata values for key '{key}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metadata values: {str(e)}"
        )


@v1_router.post("/documents/bulk-delete", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def bulk_delete_documents(request: BulkDeleteRequest):
    """
    Bulk delete documents matching filter criteria.
    
    Set preview=true to see what would be deleted without actually deleting.
    Set preview=false to perform the actual deletion.
    
    Filters support:
    - metadata.* syntax for any metadata field (e.g., {"metadata.type": "draft"})
    - Direct column names (e.g., {"document_id": "abc123"})
    - Backward compatible shortcuts (e.g., {"type": "draft"})
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        if not request.filters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one filter must be provided"
            )
        
        if request.preview:
            # Preview mode - show what would be deleted
            preview = repo.preview_delete(request.filters)
            return BulkDeletePreview(**preview)
        else:
            # Actually delete
            chunks_deleted = repo.bulk_delete(request.filters)
            return BulkDeleteResponse(
                status="success",
                chunks_deleted=chunks_deleted,
                filters_applied=request.filters
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bulk delete documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete: {str(e)}"
        )


@v1_router.post("/documents/export", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def export_documents(request: ExportRequest):
    """
    Export documents matching filter criteria as JSON backup.
    
    Use this before bulk delete to create a backup that can be restored later.
    Returns all document chunks with embeddings and metadata.
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        
        export_data = repo.export_documents(request.filters)
        
        return {
            "status": "success",
            "chunk_count": len(export_data),
            "document_count": len(set(chunk['document_id'] for chunk in export_data)),
            "filters_applied": request.filters,
            "backup_data": export_data
        }
    except Exception as e:
        logger.error(f"Failed to export documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export documents: {str(e)}"
        )


@v1_router.post("/documents/restore", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def restore_documents(request: RestoreRequest):
    """
    Restore documents from a backup (undo delete).
    
    Use the backup_data from /documents/export to restore deleted documents.
    Existing documents with same IDs will not be overwritten.
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        
        chunks_restored = repo.restore_documents(request.backup_data)
        
        return {
            "status": "success",
            "chunks_restored": chunks_restored,
            "document_count": len(set(chunk['document_id'] for chunk in request.backup_data))
        }
    except Exception as e:
        logger.error(f"Failed to restore documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore documents: {str(e)}"
        )


# ---------------------------------------------------------------------------
# API Key Management Endpoints
# ---------------------------------------------------------------------------


@v1_router.post("/api/keys", tags=["Auth"], dependencies=[Depends(require_api_key)])
async def create_key(name: str = Query(..., description="Human-readable name for the key")):
    """Create a new API key.

    The full key is returned ONCE in this response. Store it securely.
    Only the SHA-256 hash is stored server-side.
    """
    from auth import create_api_key_record
    try:
        result = create_api_key_record(name)
        return {
            "key": result["key"],
            "id": result["id"],
            "name": result["name"],
            "prefix": result["prefix"],
            "created_at": result["created_at"],
            "message": "Store this key securely. It will not be shown again.",
        }
    except Exception as e:
        logger.error(f"Failed to create API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create API key: {str(e)}",
        )


@v1_router.get("/api/keys", tags=["Auth"], dependencies=[Depends(require_api_key)])
async def list_keys():
    """List all API keys (active and revoked).

    Never returns the hash or the full key.
    """
    from auth import list_api_keys
    try:
        return {"keys": list_api_keys()}
    except Exception as e:
        logger.error(f"Failed to list API keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list API keys: {str(e)}",
        )


@v1_router.delete("/api/keys/{key_id}", tags=["Auth"], dependencies=[Depends(require_api_key)])
async def delete_key(key_id: int):
    """Revoke an API key immediately."""
    from auth import revoke_api_key
    try:
        revoked = revoke_api_key(key_id)
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Key not found or already revoked",
            )
        return {"revoked": True, "id": key_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke API key: {str(e)}",
        )


@v1_router.post("/api/keys/{key_id}/rotate", tags=["Auth"], dependencies=[Depends(require_api_key)])
async def rotate_key(key_id: int):
    """Rotate an API key.

    Creates a new key and revokes the old one with a 24-hour grace period.
    During the grace period, both old and new keys work.
    """
    from auth import rotate_api_key
    try:
        result = rotate_api_key(key_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Key not found or already revoked",
            )
        return {
            "key": result["key"],
            "id": result["id"],
            "name": result["name"],
            "prefix": result["prefix"],
            "created_at": result["created_at"],
            "old_key_id": result["old_key_id"],
            "grace_period_hours": result["grace_period_hours"],
            "message": f"Old key remains valid for {result['grace_period_hours']} hours. Store new key securely.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rotate API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rotate API key: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Indexing Health Dashboard Endpoints (#4)
# ---------------------------------------------------------------------------


@v1_router.get("/indexing/runs", tags=["Health"], dependencies=[Depends(require_api_key)])
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


@v1_router.get("/indexing/runs/summary", tags=["Health"], dependencies=[Depends(require_api_key)])
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


@v1_router.get("/indexing/runs/{run_id}", tags=["Health"], dependencies=[Depends(require_api_key)])
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


# ---------------------------------------------------------------------------
# Client Identity Endpoints (#8)
# ---------------------------------------------------------------------------


@v1_router.post("/clients/register", tags=["Clients"], dependencies=[Depends(require_api_key)])
async def register_client_endpoint(request: Request):
    """Register or update a client identity.

    Body: { "client_id": "...", "display_name": "...", "os_type": "...", "app_version": "..." }
    """
    from client_identity import register_client
    try:
        body = await request.json()
        client_id = body.get("client_id")
        display_name = body.get("display_name", "Unknown")
        os_type = body.get("os_type", "unknown")
        app_version = body.get("app_version")

        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id is required",
            )

        result = register_client(
            client_id=client_id,
            display_name=display_name,
            os_type=os_type,
            app_version=app_version,
        )
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register client",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register client: {str(e)}",
        )


@v1_router.post("/clients/heartbeat", tags=["Clients"], dependencies=[Depends(require_api_key)])
async def client_heartbeat_endpoint(request: Request):
    """Update last_seen_at for a client.

    Body: { "client_id": "...", "app_version": "..." }
    """
    from client_identity import heartbeat
    try:
        body = await request.json()
        client_id = body.get("client_id")
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id is required",
            )
        app_version = body.get("app_version")
        success = heartbeat(client_id, app_version=app_version)
        return {"ok": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to heartbeat client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to heartbeat: {str(e)}",
        )


@v1_router.get("/clients", tags=["Clients"], dependencies=[Depends(require_api_key)])
async def list_clients_endpoint():
    """List all registered clients, most recently seen first."""
    from client_identity import list_clients
    try:
        clients = list_clients()
        return {"clients": clients, "count": len(clients)}
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list clients: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Mount versioned router at /api/v1 (canonical) and / (backward compat)
# ---------------------------------------------------------------------------
app.include_router(v1_router, prefix="/api/v1")
app.include_router(v1_router)  # backward compat: old unversioned paths


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": str(exc)
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
