"""
Search, Document, and Metadata routes for PGVectorRAGIndexer.
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api_models import (
    SearchRequest, SearchResponse, SearchResultModel,
    DocumentInfo, DocumentListResponse, BulkDeleteRequest,
    ExportRequest, RestoreRequest
)
from services import get_indexer, get_retriever
from auth import require_api_key
from database import get_db_manager, DocumentRepository
from embeddings import get_embedding_service

logger = logging.getLogger(__name__)

search_router = APIRouter(tags=["Search & Documents"])


@search_router.post("/search", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
async def search_documents(request: SearchRequest):
    """Search for relevant documents."""
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


@search_router.get("/documents", response_model=DocumentListResponse, tags=["Documents"], dependencies=[Depends(require_api_key)])
async def list_documents(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="indexed_at"),
    sort_dir: str = Query(default="desc"),
    source_prefix: Optional[str] = Query(default=None),
):
    """List all indexed documents."""
    try:
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
                source_prefix=source_prefix,
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal Server Error: {str(e)}"
        )


@search_router.get("/documents/encrypted", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def list_encrypted_pdfs(
    since: Optional[str] = Query(default=None),
    clear: bool = Query(default=False)
):
    """List encrypted PDFs that were skipped during indexing."""
    from services import encrypted_pdfs_encountered
    
    result = encrypted_pdfs_encountered.copy()
    
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
    
    if clear:
        from services import encrypted_pdfs_encountered as epfe
        epfe.clear()
    
    return {
        "count": len(result),
        "encrypted_pdfs": result
    }


@search_router.get("/documents/tree", tags=["Document Tree"], dependencies=[Depends(require_api_key)])
async def get_document_tree(
    parent_path: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Get one level of the document tree."""
    from document_tree import get_tree_children
    try:
        result = get_tree_children(parent_path=parent_path, limit=limit, offset=offset)
        return result
    except Exception as e:
        logger.error(f"Failed to get document tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document tree: {str(e)}",
        )


@search_router.get("/documents/tree/stats", tags=["Document Tree"], dependencies=[Depends(require_api_key)])
async def get_document_tree_stats():
    """Get overall document tree statistics."""
    from document_tree import get_tree_stats
    try:
        return get_tree_stats()
    except Exception as e:
        logger.error(f"Failed to get tree stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tree stats: {str(e)}",
        )


@search_router.get("/documents/tree/search", tags=["Document Tree"], dependencies=[Depends(require_api_key)])
async def search_document_tree(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Search for documents matching a path pattern."""
    from document_tree import search_tree
    try:
        results = search_tree(query=q, limit=limit)
        return {"results": results, "count": len(results), "query": q}
    except Exception as e:
        logger.error(f"Failed to search document tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search tree: {str(e)}",
        )


@search_router.get("/documents/{document_id}", response_model=DocumentInfo, tags=["Documents"], dependencies=[Depends(require_api_key)])
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
            metadata=doc.get('metadata')
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@search_router.delete("/documents/{document_id}", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def delete_document(document_id: str):
    """Delete a document by ID."""
    try:
        idx = get_indexer()
        if not idx.delete_document(document_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document not found: {document_id}"
            )
        return {"status": "success", "message": f"Document deleted: {document_id}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


@search_router.get("/statistics", tags=["General"], dependencies=[Depends(require_api_key)])
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


@search_router.get("/context", tags=["RAG"], dependencies=[Depends(require_api_key)])
async def get_context(
    query: str = Query(...),
    top_k: int = Query(default=5, ge=1, le=20),
    use_hybrid: bool = Query(default=False)
):
    """Get concatenated context for RAG applications."""
    try:
        ret = get_retriever()
        context = ret.get_context(query, top_k=top_k, use_hybrid=use_hybrid)
        return {"query": query, "context": context, "chunks_used": top_k}
    except Exception as e:
        logger.error(f"Failed to get context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get context: {str(e)}"
        )


@search_router.get("/metadata/keys", response_model=List[str], tags=["Metadata"], dependencies=[Depends(require_api_key)])
async def get_metadata_keys(pattern: Optional[str] = Query(default=None)):
    """List all unique metadata keys."""
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


@search_router.get("/metadata/values", response_model=List[str], tags=["Metadata"], dependencies=[Depends(require_api_key)])
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


@search_router.post("/documents/bulk-delete", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def bulk_delete_documents(request: BulkDeleteRequest):
    """Bulk delete documents matching filter criteria."""
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
            from api_models import BulkDeletePreview as BDP
            return BDP(**preview)
        else:
            # Actually delete
            chunks_deleted = repo.bulk_delete(request.filters)
            from api_models import BulkDeleteResponse as BDR
            return BDR(
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


@search_router.post("/documents/export", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def export_documents(request: ExportRequest):
    """Export documents matching filter criteria as JSON backup."""
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


@search_router.post("/documents/restore", tags=["Documents"], dependencies=[Depends(require_api_key)])
async def restore_documents(request: RestoreRequest):
    """Restore documents from a backup."""
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
