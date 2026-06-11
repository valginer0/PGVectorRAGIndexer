"""
Search, Document, and Metadata routes for PGVectorRAGIndexer.
"""

import logging
import re
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api_models import (
    SearchRequest, SearchResponse, SearchResultModel,
    DocumentInfo, DocumentListResponse, BulkDeleteRequest,
    ExportRequest, RestoreRequest, APIErrorResponse
)
from services import get_indexer, get_retriever
from retriever_v2 import LanceDBNotReadyError
from auth import require_api_key, require_admin, require_permission
from database import get_db_manager, DocumentRepository
from embeddings import get_embedding_service

logger = logging.getLogger(__name__)

search_router = APIRouter(tags=["Search & Documents"])

DEFAULT_LITERAL_ANCHOR_THRESHOLD = 10.0
DEFAULT_LITERAL_TAIL_THRESHOLD = 0.1
DEFAULT_FUSION_LITERAL_ANCHOR_THRESHOLD = 0.01
DEFAULT_FUSION_LITERAL_TAIL_THRESHOLD = 0.005
DOCUMENT_GROUPING_BACKEND_MULTIPLIER = 20
HYBRID_MODE_LEGACY = "legacy"
HYBRID_MODE_LEXICAL_FUSION_V0 = "lexical-fusion-v0"
HYBRID_MODE_RERANK_V0 = "rerank-v0"
SUPPORTED_HYBRID_MODES = {
    HYBRID_MODE_LEGACY,
    HYBRID_MODE_LEXICAL_FUSION_V0,
    HYBRID_MODE_RERANK_V0,
}


def _result_rank_score(result: Any) -> float:
    rank_score = getattr(result, "rank_score", None)
    if rank_score is not None:
        return float(rank_score)
    return float(getattr(result, "relevance_score", 0.0) or 0.0)


def _identifier_query_tokens(query: str) -> List[str]:
    identifiers = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query):
        has_digit = any(char.isdigit() for char in token)
        has_connector = "-" in token or "_" in token
        has_alpha = any(char.isalpha() for char in token)
        is_upper_acronym = (
            has_alpha
            and token.upper() == token
            and token.lower() != token
            and 2 <= len(token) <= 5
        )
        if has_digit or has_connector or is_upper_acronym:
            identifiers.append(token.lower())
    return identifiers


def _text_contains_tokens(text: str, tokens: List[str]) -> bool:
    haystack = text.lower()
    return bool(tokens) and all(token in haystack for token in tokens)


def _group_results_by_source_uri(results: List[Any]) -> List[Any]:
    best_by_source: Dict[str, tuple[int, Any]] = {}
    for index, result in enumerate(results):
        source_uri = getattr(result, "source_uri", None) or getattr(result, "document_id", None)
        if not source_uri:
            continue
        current = best_by_source.get(source_uri)
        if current is None or _result_rank_score(result) > _result_rank_score(current[1]):
            best_by_source[source_uri] = (index, result)

    return [
        result
        for _, result in sorted(
            best_by_source.values(),
            key=lambda pair: (-_result_rank_score(pair[1]), pair[0]),
        )
    ]


def _apply_identifier_tail_suppression(
    *,
    query: str,
    chunk_results: List[Any],
    file_results: List[Any],
    anchor_threshold: float,
    tail_threshold: float,
) -> tuple[List[Any], Dict[str, Any]]:
    tokens = _identifier_query_tokens(query)
    diagnostics: Dict[str, Any] = {
        "mode": "identifier-token",
        "active": False,
        "anchor_threshold": anchor_threshold,
        "tail_threshold": tail_threshold,
        "identifier_tokens": tokens,
        "strong_literal_hits": [],
        "suppressed_count": 0,
        "suppressed_preview": [],
    }
    if not tokens:
        diagnostics["reason"] = "no_identifier_tokens"
        return file_results, diagnostics

    literal_sources = {
        source_uri
        for result in chunk_results
        if (source_uri := getattr(result, "source_uri", None))
        and _text_contains_tokens(getattr(result, "text_content", ""), tokens)
    }
    if not literal_sources:
        diagnostics["reason"] = "no_literal_hits"
        return file_results, diagnostics

    strong_literal_hits = []
    for rank, result in enumerate(file_results, start=1):
        source_uri = getattr(result, "source_uri", None)
        rank_score = _result_rank_score(result)
        if source_uri in literal_sources and rank_score >= anchor_threshold:
            strong_literal_hits.append({
                "rank": rank,
                "source_uri": source_uri,
                "rank_score": rank_score,
            })

    diagnostics["strong_literal_hits"] = strong_literal_hits
    if not strong_literal_hits:
        diagnostics["reason"] = "no_strong_literal_hit"
        return file_results, diagnostics

    kept = []
    suppressed = []
    for rank, result in enumerate(file_results, start=1):
        source_uri = getattr(result, "source_uri", None)
        rank_score = _result_rank_score(result)
        if source_uri not in literal_sources and rank_score < tail_threshold:
            suppressed.append({
                "rank": rank,
                "source_uri": source_uri,
                "rank_score": rank_score,
            })
            continue
        kept.append(result)

    diagnostics.update({
        "active": True,
        "reason": "strong_literal_hit",
        "suppressed_count": len(suppressed),
        "suppressed_preview": suppressed[:10],
    })
    return kept, diagnostics


def _apply_access_filters(key_record: Optional[dict], base_filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Merge per-user access-control filters into request filters.

    Injects the visibility exclusion list and collection-grant namespace
    allowlist for the calling identity. Fails closed — a DB error aborts the
    request rather than leaking. Client-supplied allowed_namespaces is
    overwritten; it must never widen access.
    """
    from document_visibility import search_exclusions_for_key_record
    from collection_grants import search_allowed_namespaces_for_key_record

    effective_filters = dict(base_filters) if base_filters else {}

    excluded_ids = search_exclusions_for_key_record(key_record)
    if excluded_ids:
        effective_filters["excluded_document_ids"] = excluded_ids

    allowed_namespaces = search_allowed_namespaces_for_key_record(key_record)
    if allowed_namespaces is not None:
        effective_filters["allowed_namespaces"] = allowed_namespaces
    elif "allowed_namespaces" in effective_filters:
        del effective_filters["allowed_namespaces"]

    return effective_filters or None


@search_router.post("/search", response_model=SearchResponse, responses={401: {"model": APIErrorResponse}})
async def search_documents(
    request: SearchRequest,
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Search for relevant documents.

    Results are visibility-filtered: private documents owned by another user
    are excluded from the searching user's results (admins see everything;
    local/no-auth mode is unfiltered).
    """
    try:
        if request.hybrid_mode is not None:
            if not request.use_hybrid:
                raise ValueError("hybrid_mode requires use_hybrid=true")
            if request.hybrid_mode not in SUPPORTED_HYBRID_MODES:
                raise ValueError(
                    "hybrid_mode currently supports only legacy, lexical-fusion-v0, or rerank-v0"
                )
        if request.literal_tail_suppression and not request.group_by_document:
            raise ValueError("literal_tail_suppression requires group_by_document=true")
        if request.literal_tail_suppression not in (None, "identifier-token"):
            raise ValueError("literal_tail_suppression currently supports only identifier-token")
        # Dynamically assign default thresholds depending on whether hybrid fusion-v0 is used.
        # This is because lexical-fusion-v0 produces normalized reciprocal rank fusion (RRF) scores
        # that are strictly less than 1.0 (typically < 0.033), in contrast to legacy hybrid which
        # produces scores > 10.0.
        is_fusion = request.use_hybrid and request.hybrid_mode == HYBRID_MODE_LEXICAL_FUSION_V0
        default_anchor = (
            DEFAULT_FUSION_LITERAL_ANCHOR_THRESHOLD
            if is_fusion
            else DEFAULT_LITERAL_ANCHOR_THRESHOLD
        )
        default_tail = (
            DEFAULT_FUSION_LITERAL_TAIL_THRESHOLD
            if is_fusion
            else DEFAULT_LITERAL_TAIL_THRESHOLD
        )

        literal_anchor_threshold = (
            request.literal_anchor_threshold
            if request.literal_anchor_threshold is not None
            else default_anchor
        )
        literal_tail_threshold = (
            request.literal_tail_threshold
            if request.literal_tail_threshold is not None
            else default_tail
        )
        if literal_anchor_threshold < 0:
            raise ValueError("literal_anchor_threshold must be non-negative")
        if literal_tail_threshold < 0:
            raise ValueError("literal_tail_threshold must be non-negative")

        ret = get_retriever()

        effective_filters = _apply_access_filters(key_record, request.filters)

        start_time = time.time()
        search_top_k = request.top_k
        if request.group_by_document and request.top_k:
            search_top_k = request.top_k * DOCUMENT_GROUPING_BACKEND_MULTIPLIER

        from config import get_config
        config = get_config()

        retrieval_diagnostics = None
        if ret._should_use_lancedb(source=request.source):
            results, retrieval_diagnostics = ret.search_lancedb_parent_child(
                query=request.query,
                top_k=search_top_k,
                filters=effective_filters
            )
        elif request.use_hybrid:
            if request.hybrid_mode == HYBRID_MODE_LEXICAL_FUSION_V0:
                fusion_search = getattr(ret, "search_hybrid_fusion_v0", None)
                if fusion_search is None:
                    raise ValueError(
                        "hybrid_mode lexical-fusion-v0 is not implemented by the configured retriever"
                    )
                results, retrieval_diagnostics = fusion_search(
                    query=request.query,
                    top_k=search_top_k,
                    alpha=request.alpha,
                    filters=effective_filters,
                )
            elif request.hybrid_mode == HYBRID_MODE_RERANK_V0:
                rerank_search = getattr(ret, "search_hybrid_rerank_v0", None)
                if rerank_search is None:
                    raise ValueError(
                        "hybrid_mode rerank-v0 is not implemented by the configured retriever"
                    )
                results, retrieval_diagnostics = rerank_search(
                    query=request.query,
                    top_k=search_top_k,
                    alpha=request.alpha,
                    filters=effective_filters,
                )
            else:
                results = ret.search_hybrid(
                    query=request.query,
                    top_k=search_top_k,
                    alpha=request.alpha,
                    filters=effective_filters,
                    source=request.source,
                )
        else:
            results = ret.search(
                query=request.query,
                top_k=search_top_k,
                filters=effective_filters,
                min_score=request.min_score,
                source=request.source,
            )

        diagnostics = dict(retrieval_diagnostics) if retrieval_diagnostics else None
        if request.group_by_document:
            raw_result_count = len(results)
            grouped_results = _group_results_by_source_uri(results)
            diagnostics = diagnostics or {}
            diagnostics["group_by_document"] = {
                "active": True,
                "raw_result_count": raw_result_count,
                "grouped_result_count": len(grouped_results),
                "requested_top_k": request.top_k,
                "backend_top_k": search_top_k,
            }
            if request.literal_tail_suppression == "identifier-token":
                grouped_results, suppression_diagnostics = _apply_identifier_tail_suppression(
                    query=request.query,
                    chunk_results=results,
                    file_results=grouped_results,
                    anchor_threshold=literal_anchor_threshold,
                    tail_threshold=literal_tail_threshold,
                )
                diagnostics["literal_tail_suppression"] = suppression_diagnostics
                diagnostics["group_by_document"]["suppressed_grouped_result_count"] = len(grouped_results)
            results = grouped_results[:request.top_k] if request.top_k else grouped_results
        search_time = (time.time() - start_time) * 1000  # Convert to ms

        # Check active index document count for state-aware search messages
        total_documents = 0
        if ret._should_use_lancedb(source=request.source):
            try:
                from services import get_lancedb_adapter
                total_documents = get_lancedb_adapter().get_statistics().get("total_documents", 0)
            except Exception:
                pass
        else:
            try:
                from document_tree import get_tree_stats
                total_documents = get_tree_stats(source="postgres").get("total_documents", 0)
            except Exception:
                pass

        message = None
        if total_documents == 0:
            if ret._should_use_lancedb(source=request.source):
                message = "The search index is empty. See the Documents tab → switch to the LanceDB view."
            else:
                message = "The search index is empty. See the Documents tab."

        result_models = [
            SearchResultModel(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                chunk_index=r.chunk_index,
                text_content=r.text_content,
                source_uri=r.source_uri,
                distance=r.distance,
                relevance_score=r.relevance_score,
                rank_score=r.rank_score,
                metadata=r.metadata,
                document_type=r.document_type
            )
            for r in results
        ]

        return SearchResponse(
            query=request.query,
            results=result_models,
            total_results=len(result_models),
            search_time_ms=round(search_time, 2),
            diagnostics=diagnostics,
            message=message,
        )
    except LanceDBNotReadyError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@search_router.get("/documents", response_model=DocumentListResponse, tags=["Documents"], responses={401: {"model": APIErrorResponse}})
async def list_documents(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="indexed_at"),
    sort_dir: str = Query(default="desc"),
    source_prefix: Optional[str] = Query(default=None),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """List indexed documents visible to the caller."""
    from document_visibility import visibility_clause_for_key_record
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
                with_total=True,
                visibility=visibility_clause_for_key_record(key_record)
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


@search_router.get("/documents/encrypted", tags=["Documents"])
async def list_encrypted_pdfs(
    since: Optional[str] = Query(default=None),
    clear: bool = Query(default=False),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """List encrypted PDFs that were skipped during indexing.

    Non-admin callers only see (and clear) entries from their own uploads.
    """
    from services import encrypted_pdfs_encountered
    from document_visibility import is_admin_key_record

    is_admin = is_admin_key_record(key_record)

    def _own_entry(item: dict) -> bool:
        return isinstance(key_record, dict) and item.get("uploader_key_id") == key_record["id"]

    result = [
        item for item in encrypted_pdfs_encountered
        if is_admin or _own_entry(item)
    ]

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
        if is_admin:
            epfe.clear()
        else:
            epfe[:] = [item for item in epfe if not _own_entry(item)]

    return {
        "count": len(result),
        "encrypted_pdfs": result
    }


def _tree_read_filters(key_record: Optional[dict], source: str):
    """Visibility filters for tree reads: SQL clause for Postgres, hidden-id
    exclusion list for LanceDB (which has no visibility columns)."""
    from document_visibility import (
        visibility_clause_for_key_record,
        search_exclusions_for_key_record,
    )
    visibility = visibility_clause_for_key_record(key_record)
    hidden_ids = search_exclusions_for_key_record(key_record) if source == "lancedb" else None
    return visibility, hidden_ids


@search_router.get("/documents/tree", tags=["Document Tree"])
async def get_document_tree(
    parent_path: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    source: str = Query(default="postgres"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get one level of the document tree (visibility-filtered)."""
    from document_tree import get_tree_children
    try:
        visibility, hidden_ids = _tree_read_filters(key_record, source)
        result = get_tree_children(
            parent_path=parent_path, limit=limit, offset=offset, source=source,
            visibility=visibility, hidden_document_ids=hidden_ids,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to get document tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document tree: {str(e)}",
        )


@search_router.get("/documents/tree/stats", tags=["Document Tree"])
async def get_document_tree_stats(
    source: str = Query(default="postgres"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get overall document tree statistics (visibility-filtered)."""
    from document_tree import get_tree_stats
    try:
        visibility, hidden_ids = _tree_read_filters(key_record, source)
        return get_tree_stats(
            source=source, visibility=visibility, hidden_document_ids=hidden_ids,
        )
    except Exception as e:
        logger.error(f"Failed to get tree stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tree stats: {str(e)}",
        )


@search_router.get("/documents/tree/search", tags=["Document Tree"])
async def search_document_tree(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
    source: str = Query(default="postgres"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Search for documents matching a path pattern (visibility-filtered)."""
    from document_tree import search_tree
    try:
        visibility, hidden_ids = _tree_read_filters(key_record, source)
        results = search_tree(
            query=q, limit=limit, source=source,
            visibility=visibility, hidden_document_ids=hidden_ids,
        )
        return {"results": results, "count": len(results), "query": q}
    except Exception as e:
        logger.error(f"Failed to search document tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search tree: {str(e)}",
        )


@search_router.get("/documents/{document_id}", response_model=DocumentInfo, tags=["Documents"])
async def get_document(
    document_id: str,
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get document information by ID. Hidden documents return 404."""
    from document_visibility import visibility_clause_for_key_record
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        doc = repo.get_document_by_id(
            document_id,
            visibility=visibility_clause_for_key_record(key_record),
        )

        if not doc:
            from errors import raise_api_error, ErrorCode
            raise_api_error(
                ErrorCode.DOCUMENT_NOT_FOUND,
                message=f"Document not found: {document_id}"
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


@search_router.delete("/documents/{document_id}", tags=["Documents"], dependencies=[Depends(require_permission("documents.delete"))])
async def delete_document(document_id: str):
    """Delete a document by ID. Requires the documents.delete permission."""
    try:
        idx = get_indexer()
        if not idx.delete_document(document_id):
            from errors import raise_api_error, ErrorCode
            raise_api_error(
                ErrorCode.DOCUMENT_NOT_FOUND,
                message=f"Document not found: {document_id}"
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


@search_router.get("/statistics", tags=["General"])
async def get_statistics(
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get system statistics. Document/chunk counts cover visible documents only."""
    from document_visibility import visibility_clause_for_key_record
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        stats = repo.get_statistics(visibility=visibility_clause_for_key_record(key_record))

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


@search_router.get("/context", tags=["RAG"])
async def get_context(
    query: str = Query(...),
    top_k: int = Query(default=5, ge=1, le=20),
    use_hybrid: bool = Query(default=False),
    source: str = Query(default="lancedb"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Get concatenated context for RAG applications.

    Visibility-filtered like /search: other users' private documents and
    namespaces outside the caller's collection grants are excluded.
    """
    try:
        ret = get_retriever()
        access_filters = _apply_access_filters(key_record, None)
        context = ret.get_context(
            query, top_k=top_k, use_hybrid=use_hybrid, source=source,
            filters=access_filters,
        )
        return {"query": query, "context": context, "chunks_used": top_k}
    except LanceDBNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to get context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get context: {str(e)}"
        )


@search_router.get("/extensions", response_model=List[str], tags=["Search & Documents"])
async def get_indexed_extensions(
    key_record: Optional[dict] = Depends(require_api_key),
):
    """Return sorted list of distinct file extensions among visible documents."""
    from document_visibility import visibility_clause_for_key_record
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        return repo.get_indexed_extensions(visibility=visibility_clause_for_key_record(key_record))
    except Exception as e:
        logger.error(f"Failed to get indexed extensions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get indexed extensions: {str(e)}"
        )


@search_router.get("/metadata/keys", response_model=List[str], tags=["Metadata"])
async def get_metadata_keys(
    pattern: Optional[str] = Query(default=None),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """List unique metadata keys among visible documents."""
    from document_visibility import visibility_clause_for_key_record
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        keys = repo.get_metadata_keys(
            pattern=pattern,
            visibility=visibility_clause_for_key_record(key_record),
        )
        return keys
    except Exception as e:
        logger.error(f"Failed to get metadata keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metadata keys: {str(e)}"
        )


@search_router.get("/metadata/values", response_model=List[str], tags=["Metadata"])
async def get_metadata_values(
    key: str = Query(..., description="Metadata key to get values for"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum values to return"),
    key_record: Optional[dict] = Depends(require_api_key),
):
    """
    Get unique values for a specific metadata key among visible documents.

    Useful for building filter dropdowns in UI.
    """
    from document_visibility import visibility_clause_for_key_record
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        values = repo.get_metadata_values(
            key=key,
            limit=limit,
            visibility=visibility_clause_for_key_record(key_record),
        )
        return values
    except Exception as e:
        logger.error(f"Failed to get metadata values for key '{key}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metadata values: {str(e)}"
        )


@search_router.post("/documents/bulk-delete", tags=["Documents"], dependencies=[Depends(require_permission("documents.delete"))])
async def bulk_delete_documents(request: BulkDeleteRequest):
    """Bulk delete documents matching filter criteria. Requires documents.delete."""
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
            from config import get_config
            config = get_config()
            mutation_active = bool(getattr(config.retrieval, "lancedb_enabled", False))
            if mutation_active:
                from retriever_v2 import begin_lancedb_mutation
                begin_lancedb_mutation()
            try:
                # Dual-delete from LanceDB first if enabled to prevent split-brain if LanceDB fails
                if getattr(config.retrieval, "lancedb_enabled", False):
                    try:
                        from services import get_lancedb_adapter
                        get_lancedb_adapter().bulk_delete(request.filters)
                    except Exception as e:
                        logger.error(f"Failed to bulk delete from LanceDB: {e}", exc_info=True)
                        from retriever_v2 import invalidate_lancedb_cache
                        invalidate_lancedb_cache()
                        raise

                chunks_deleted = repo.bulk_delete(request.filters)

                # Invalidate readiness cache on successful delete
                from retriever_v2 import invalidate_lancedb_cache
                invalidate_lancedb_cache()
            finally:
                if mutation_active:
                    from retriever_v2 import end_lancedb_mutation
                    end_lancedb_mutation()

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


@search_router.post("/documents/export", tags=["Documents"], dependencies=[Depends(require_admin)])
async def export_documents(request: ExportRequest):
    """Export documents matching filter criteria as JSON backup.

    Admin only: the export contains full chunk text of ALL matching
    documents regardless of visibility, so it must not be exposed to
    regular users. (Filtering the export instead would silently produce
    incomplete backups, which is worse.)
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


@search_router.post("/documents/restore", tags=["Documents"], dependencies=[Depends(require_admin)])
async def restore_documents(request: RestoreRequest):
    """Restore documents from a backup.

    Admin only (symmetric with /documents/export): restore overwrites
    existing documents by document_id with caller-supplied content and
    embeddings — including other users' private documents — so it must not
    be exposed to regular users.

    Note: if the LanceDB dual-write fails mid-restore, the compensating
    rollback deletes the restored documents entirely (to keep the two stores
    count-consistent) — including any pre-existing version a restore had
    overwritten. Re-run the restore after fixing the failure.
    """
    try:
        db_manager = get_db_manager()
        repo = DocumentRepository(db_manager)
        from config import get_config
        config = get_config()
        mutation_active = bool(getattr(config.retrieval, "lancedb_enabled", False))
        if mutation_active:
            from retriever_v2 import begin_lancedb_mutation
            begin_lancedb_mutation()
        try:
            chunks_restored = repo.restore_documents(request.backup_data)

            # Dual-restore to LanceDB if enabled
            if getattr(config.retrieval, "lancedb_enabled", False):
                from services import get_lancedb_adapter
                adapter = get_lancedb_adapter()

                # Group chunks by document_id
                docs_chunks = {}
                docs_meta = {}
                docs_uri = {}

                for chunk in request.backup_data:
                    doc_id = chunk["document_id"]
                    if doc_id not in docs_chunks:
                        docs_chunks[doc_id] = []
                        docs_meta[doc_id] = chunk.get("metadata") or {}
                        docs_uri[doc_id] = chunk["source_uri"]

                    docs_chunks[doc_id].append((
                        chunk["chunk_index"],
                        chunk["text_content"],
                        chunk["embedding"],
                        chunk.get("metadata") or {}
                    ))

                for doc_id, c_list in docs_chunks.items():
                    c_list.sort(key=lambda x: x[0])
                    aggregated_text = "\n\n".join(x[1] for x in c_list)
                    adapter.upsert_document(
                        document_id=doc_id,
                        source_uri=docs_uri[doc_id],
                        chunks=c_list,
                        aggregated_text=aggregated_text,
                        doc_metadata=docs_meta[doc_id]
                    )

            # Invalidate readiness cache on successful restore
            from retriever_v2 import invalidate_lancedb_cache
            invalidate_lancedb_cache()
        except Exception as e:
            logger.error(f"Failed to restore documents to LanceDB-backed stores: {e}. Rolling back PostgreSQL if needed...", exc_info=True)
            try:
                doc_ids = set(chunk["document_id"] for chunk in request.backup_data)
                for doc_id in doc_ids:
                    repo.delete_document(doc_id)
            except Exception as rollback_err:
                logger.critical(f"PostgreSQL rollback restore delete failed: {rollback_err}", exc_info=True)
            from retriever_v2 import invalidate_lancedb_cache
            invalidate_lancedb_cache()
            raise
        finally:
            if mutation_active:
                from retriever_v2 import end_lancedb_mutation
                end_lancedb_mutation()

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
