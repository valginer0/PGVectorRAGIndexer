"""
Pydantic models for PGVectorRAGIndexer API.

This module centralizes request and response models to be shared across 
the modular routers.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

# API Version Constants
API_VERSION = "1"                  # Current API version
MIN_CLIENT_VERSION = "2.4.0"       # Oldest desktop client that works with this API
MAX_CLIENT_VERSION = "99.99.99"    # No upper bound yet


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


class RetentionRunRequest(BaseModel):
    """Request model for retention orchestration runs."""
    activity_days: Optional[int] = Field(default=None, ge=1)
    quarantine_days: Optional[int] = Field(default=None, ge=1)
    indexing_runs_days: Optional[int] = Field(default=None, ge=1)
    cleanup_saml_sessions: bool = Field(default=True)
