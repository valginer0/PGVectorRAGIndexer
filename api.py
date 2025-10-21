"""
FastAPI REST API for PGVectorRAGIndexer.

Provides HTTP endpoints for indexing, searching, and managing documents.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_config
from database import get_db_manager, close_db_manager, DocumentRepository
from embeddings import get_embedding_service
from document_processor import DocumentProcessor, UnsupportedFormatError, DocumentProcessingError
from indexer_v2 import DocumentIndexer
from retriever_v2 import DocumentRetriever, SearchResult

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


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    logger.info("Starting PGVectorRAGIndexer API...")
    try:
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


# Create FastAPI app
config = get_config()
app = FastAPI(
    title="PGVectorRAGIndexer API",
    description="REST API for semantic document search using PostgreSQL and pgvector",
    version="2.0.0",
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

# Mount static files for web UI
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize services (will be created on first request)
indexer: Optional[DocumentIndexer] = None
retriever: Optional[DocumentRetriever] = None


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


@app.get("/api", tags=["General"])
async def api_info():
    """API information endpoint."""
    return {
        "name": "PGVectorRAGIndexer API",
        "version": "2.0.0",
        "description": "Semantic document search using PostgreSQL and pgvector",
        "docs": "/docs",
        "health": "/health"
    }


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


@app.get("/stats", response_model=StatsResponse, tags=["General"])
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


@app.post("/index", response_model=IndexResponse, tags=["Indexing"])
async def index_document(request: IndexRequest):
    """Index a document from URI."""
    try:
        idx = get_indexer()
        result = idx.index_document(
            source_uri=request.source_uri,
            force_reindex=request.force_reindex,
            custom_metadata=request.metadata
        )
        
        if result['status'] == 'error':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result['message']
            )
        
        return IndexResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Indexing failed: {str(e)}"
        )


@app.post("/upload-and-index", response_model=IndexResponse, tags=["Indexing"])
async def upload_and_index(
    file: UploadFile = File(...),
    force_reindex: bool = Form(default=False),
    custom_source_uri: Optional[str] = Form(default=None),
    document_type: Optional[str] = Form(default=None)
):
    """
    Upload a file and index it immediately.
    
    This endpoint allows you to index files from any location on your system
    without needing to copy them to the documents directory first.
    
    Args:
        file: The file to upload and index
        force_reindex: Force reindex if file already exists
        
    Returns:
        IndexResponse with indexing results
        
    Example:
        curl -X POST "http://localhost:8000/upload-and-index" \\
          -F "file=@C:\\Users\\YourName\\Documents\\file.pdf"
    """
    import tempfile
    import os
    
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
            custom_metadata=metadata
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
        
        return IndexResponse(
            status='success',
            document_id=processed_doc.document_id,
            source_uri=processed_doc.source_uri,
            chunks_indexed=len(chunks_data)
        )
        
    except HTTPException:
        raise
    except (UnsupportedFormatError, DocumentProcessingError) as e:
        logger.error(f"Upload and index failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
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


@app.post("/search", response_model=SearchResponse, tags=["Search"])
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
                relevance_score=r.relevance_score
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


@app.get("/documents", response_model=List[DocumentInfo], tags=["Documents"])
async def list_documents(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum documents to return"),
    offset: int = Query(default=0, ge=0, description="Number of documents to skip")
):
    """List all indexed documents."""
    try:
        idx = get_indexer()
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        
        documents = repo.list_documents(limit=limit, offset=offset)
        
        return [
            DocumentInfo(
                document_id=doc['document_id'],
                source_uri=doc['source_uri'],
                chunk_count=doc['chunk_count'],
                indexed_at=doc['indexed_at'],
                last_updated=doc.get('last_updated'),
                document_type=doc.get('document_type')
            )
            for doc in documents
        ]
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {str(e)}"
        )


@app.get("/documents/{document_id}", response_model=DocumentInfo, tags=["Documents"])
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
            indexed_at=doc['indexed_at']
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@app.delete("/documents/{document_id}", tags=["Documents"])
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


@app.get("/statistics", tags=["General"])
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


@app.get("/context", tags=["RAG"])
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


@app.get("/metadata/keys", response_model=List[str], tags=["Metadata"])
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


@app.get("/metadata/values", response_model=List[str], tags=["Metadata"])
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


@app.post("/documents/bulk-delete", tags=["Documents"])
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
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to bulk delete documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete: {str(e)}"
        )


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
