"""
Improved retriever with hybrid search, filtering, and better result formatting.

This is the v2 retriever that uses the new modular architecture.
"""

import argparse
import logging
import math
import re
import sys
import threading
import time
from typing import List, Dict, Any, Optional, Tuple, Mapping
from dataclasses import dataclass, replace

from config import get_config
from database import get_db_manager, DocumentRepository
from embeddings import get_embedding_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FUSION_V0_RRF_K = 60
FUSION_V0_DENSE_WEIGHT = 1.0
FUSION_V0_LEXICAL_WEIGHT = 1.0
RERANK_V0_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_V0_CANDIDATE_MULTIPLIER = 10
RERANK_V0_MIN_CANDIDATES = 50
RERANK_V0_MAX_CANDIDATES = 200


def parse_search_query(query: str) -> Tuple[List[str], List[str]]:
    """
    Parse a search query to extract quoted phrases and regular terms.

    Supports multiple quote styles:
    - Double quotes: "exact phrase"
    - Single quotes: 'exact phrase'
    - Smart/curly quotes: "phrase" or 'phrase'

    Args:
        query: Search string, potentially with quoted phrases

    Returns:
        Tuple of (phrases, terms) where:
        - phrases: List of exact phrase strings (without quotes)
        - terms: List of unquoted search terms
    """
    # Match all quote styles: "...", '...', "...", '...'
    quote_pattern = r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]|[\'\u2018\u2019]([^\'\u2018\u2019]+)[\'\u2018\u2019]'

    phrases = []
    for match in re.finditer(quote_pattern, query):
        # Either group 1 (double quotes) or group 2 (single quotes) will have content
        phrase = match.group(1) or match.group(2)
        if phrase and phrase.strip():
            phrases.append(phrase.strip())

    # Remove all quoted phrases to get remaining terms
    terms_text = re.sub(quote_pattern, '', query).strip()
    terms = terms_text.split() if terms_text else []
    return phrases, terms


def normalize_lexical_terms(values: List[str]) -> List[str]:
    """Normalize query fragments into exact-match lexical terms."""
    terms: List[str] = []
    seen = set()
    for value in values:
        for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
            term = match.group(0).lower()
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def build_exact_token_regex(term: str) -> str:
    """Build a PostgreSQL regex pattern for case-insensitive exact-token matching."""
    return rf"(^|[^[:alnum:]_]){re.escape(term.lower())}([^[:alnum:]_]|$)"


def calculate_idf(total_documents: int, document_frequency: int) -> float:
    """Calculate smoothed IDF for document-level lexical rarity."""
    if total_documents < 0:
        raise ValueError("total_documents must be non-negative")
    if document_frequency < 0:
        raise ValueError("document_frequency must be non-negative")
    if document_frequency > total_documents:
        raise ValueError("document_frequency cannot exceed total_documents")
    return math.log((total_documents + 1) / (document_frequency + 1)) + 1


def weighted_rrf_score(
    *,
    dense_rank: Optional[int] = None,
    lexical_rank: Optional[int] = None,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> float:
    """Compute a weighted Reciprocal Rank Fusion score."""
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")
    score = 0.0
    if dense_rank is not None:
        if dense_rank < 1:
            raise ValueError("dense_rank must be positive")
        score += dense_weight * (1.0 / (rrf_k + dense_rank))
    if lexical_rank is not None:
        if lexical_rank < 1:
            raise ValueError("lexical_rank must be positive")
        score += lexical_weight * (1.0 / (rrf_k + lexical_rank))
    return score


def fuse_ranked_candidates(
    dense_ranks: Mapping[int, int],
    lexical_ranks: Mapping[int, int],
    *,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> List[Tuple[int, float]]:
    """Fuse dense and lexical chunk ranks into sorted `(chunk_id, score)` pairs."""
    chunk_ids = set(dense_ranks) | set(lexical_ranks)
    scored = [
        (
            chunk_id,
            weighted_rrf_score(
                dense_rank=dense_ranks.get(chunk_id),
                lexical_rank=lexical_ranks.get(chunk_id),
                rrf_k=rrf_k,
                dense_weight=dense_weight,
                lexical_weight=lexical_weight,
            ),
        )
        for chunk_id in chunk_ids
    ]
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def rerank_v0_candidate_limit(top_k: int) -> int:
    """Calculate the legacy-hybrid candidate window for rerank-v0."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    return min(
        max(top_k * RERANK_V0_CANDIDATE_MULTIPLIER, RERANK_V0_MIN_CANDIDATES),
        RERANK_V0_MAX_CANDIDATES,
    )


def coerce_rerank_scores(raw_scores: Any, expected_count: int) -> List[float]:
    """Normalize reranker model output to one float score per candidate."""
    if hasattr(raw_scores, "tolist"):
        raw_scores = raw_scores.tolist()
    if expected_count == 1 and isinstance(raw_scores, (int, float)):
        return [float(raw_scores)]

    scores = [float(score) for score in raw_scores]
    if len(scores) != expected_count:
        raise ValueError(
            f"rerank-v0 expected {expected_count} scores, received {len(scores)}"
        )
    return scores


@dataclass
class SearchResult:
    """Container for search result data."""

    chunk_id: int
    document_id: str
    chunk_index: int
    text_content: str
    source_uri: str
    distance: float
    relevance_score: float
    rank_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    document_type: Optional[str] = None

    def __str__(self) -> str:
        """Format result as string."""
        return (
            f"Score: {self.relevance_score:.4f} | "
            f"Source: {self.source_uri} (Chunk #{self.chunk_index})\n"
            f"Text: {self.text_content[:200]}..."
        )

class LanceDBNotReadyError(Exception):
    """Exception raised when LanceDB is enabled but not ready/syncing."""
    pass

_lancedb_cache_dirty = True
_lancedb_cached_ready = False
_sync_lock = threading.Lock()
_sync_thread: Optional[threading.Thread] = None
_lancedb_current_drift_signature: Optional[Tuple[int, int, int, int]] = None
_lancedb_failed_sync_signature: Optional[Tuple[int, int, int, int]] = None
_lancedb_sync_failure_message: Optional[str] = None
_lancedb_mutation_lock = threading.Lock()
_lancedb_mutation_count = 0

def invalidate_lancedb_cache():
    """Invalidate the cached LanceDB readiness/drift status."""
    global _lancedb_cache_dirty
    _lancedb_cache_dirty = True
    logger.info("LanceDB readiness cache invalidated.")


def begin_lancedb_mutation() -> None:
    """Mark a Postgres/LanceDB dual-write mutation as active."""
    global _lancedb_mutation_count
    with _lancedb_mutation_lock:
        _lancedb_mutation_count += 1


def end_lancedb_mutation() -> None:
    """Mark a Postgres/LanceDB dual-write mutation as finished."""
    global _lancedb_mutation_count
    with _lancedb_mutation_lock:
        _lancedb_mutation_count = max(0, _lancedb_mutation_count - 1)
    invalidate_lancedb_cache()


def _lancedb_mutation_in_progress() -> bool:
    with _lancedb_mutation_lock:
        return _lancedb_mutation_count > 0


class DocumentRetriever:
    """
    Main retriever class for semantic search.

    Supports vector search, hybrid search, and filtering.
    """

    def __init__(self):
        """Initialize retriever with required services."""
        self.config = get_config()
        self.db_manager = get_db_manager()
        self.repository = DocumentRepository(self.db_manager)
        self.embedding_service = get_embedding_service()
        self._reranker_v0 = None

    def check_readiness(self) -> str:
        """
        Check LanceDB readiness status.

        Returns:
            "READY" if in sync, or "NOT_READY" if there is drift or empty with PG data.
        """
        global _lancedb_cache_dirty, _lancedb_cached_ready
        global _lancedb_current_drift_signature, _lancedb_failed_sync_signature
        global _lancedb_sync_failure_message

        if _lancedb_mutation_in_progress():
            # Serve the last known-good LanceDB index during ordinary ingestion/delete
            # mutations. If readiness was not yet established, block without kicking off
            # a whole-corpus repair sync for this expected transient drift.
            if not _lancedb_cache_dirty and _lancedb_cached_ready:
                return "READY"
            return "MUTATING"

        if not _lancedb_cache_dirty:
            return "READY" if _lancedb_cached_ready else "NOT_READY"

        try:
            from services import get_lancedb_adapter
            lancedb_adapter = get_lancedb_adapter()
            lancedb_stats = lancedb_adapter.get_statistics()
            lancedb_docs = lancedb_stats.get("total_documents", 0)
            lancedb_chunks = lancedb_stats.get("total_chunks", 0)

            pg_stats = self.repository.get_statistics()
            pg_docs = pg_stats.get("total_documents", 0)
            pg_chunks = pg_stats.get("total_chunks", 0)

            # Check for empty-with-pg-data or count drift
            if pg_docs > 0 and (lancedb_docs == 0 or pg_docs != lancedb_docs or pg_chunks != lancedb_chunks):
                drift_signature = (pg_docs, pg_chunks, lancedb_docs, lancedb_chunks)
                _lancedb_current_drift_signature = drift_signature
                logger.warning(
                    f"LanceDB drift/not ready detected! PostgreSQL has {pg_docs} docs ({pg_chunks} chunks), "
                    f"LanceDB has {lancedb_docs} docs ({lancedb_chunks} chunks)."
                )
                _lancedb_cached_ready = False
                _lancedb_cache_dirty = False
                if _lancedb_failed_sync_signature == drift_signature:
                    logger.error(
                        "LanceDB sync previously failed for the current drift signature: %s",
                        _lancedb_sync_failure_message or "unknown error",
                    )
                    return "FAILED"
                return "NOT_READY"

            # Both empty, or counts equal and populated
            _lancedb_current_drift_signature = None
            _lancedb_failed_sync_signature = None
            _lancedb_sync_failure_message = None
            _lancedb_cached_ready = True
            _lancedb_cache_dirty = False
            return "READY"
        except Exception as e:
            logger.warning(f"Error checking LanceDB status, treating as NOT_READY: {e}")
            return "NOT_READY"

    def _trigger_self_healing_sync(self) -> None:
        """Trigger background self-healing sync if not already running."""
        global _sync_thread, _sync_lock
        global _lancedb_current_drift_signature, _lancedb_failed_sync_signature
        with _sync_lock:
            if (
                _lancedb_current_drift_signature is not None
                and _lancedb_failed_sync_signature == _lancedb_current_drift_signature
            ):
                logger.error("Not starting LanceDB self-healing sync; current drift already failed to converge.")
                return
            if _sync_thread is None or not _sync_thread.is_alive():
                logger.info("Spawning background thread for self-healing LanceDB sync...")
                _sync_thread = threading.Thread(
                    target=self._run_background_sync,
                    args=(_lancedb_current_drift_signature,),
                    daemon=True,
                )
                _sync_thread.start()
            else:
                logger.info("Background self-healing LanceDB sync is already running.")

    def _run_background_sync(self, drift_signature: Optional[Tuple[int, int, int, int]] = None) -> None:
        """Run the self-healing sync in a background thread."""
        global _lancedb_failed_sync_signature, _lancedb_sync_failure_message
        try:
            from scripts.sync_lancedb import sync_postgres_to_lancedb
            sync_postgres_to_lancedb(force=True)
            _lancedb_failed_sync_signature = None
            _lancedb_sync_failure_message = None
            logger.info("Background self-healing LanceDB sync completed successfully.")
        except Exception as e:
            _lancedb_failed_sync_signature = drift_signature
            _lancedb_sync_failure_message = str(e)
            logger.error(f"Background self-healing LanceDB sync failed: {e}", exc_info=True)
        finally:
            invalidate_lancedb_cache()

    def _should_use_lancedb(self, source: str = "lancedb") -> bool:
        """
        Check if LanceDB search should be used.

        Args:
            source: Search backend override ('lancedb' or 'postgres')

        Returns:
            True if LanceDB should be used, False if fallback/override to Postgres.

        Raises:
            LanceDBNotReadyError: If LanceDB is enabled but is not ready or syncing.
        """
        if source == "postgres":
            return False

        if not getattr(self.config.retrieval, "lancedb_enabled", False):
            return False

        status = self.check_readiness()
        if status == "MUTATING":
            raise LanceDBNotReadyError("LanceDB index is updating — please wait")
        if status == "FAILED":
            raise LanceDBNotReadyError(
                f"LanceDB index sync failed: {_lancedb_sync_failure_message or 'manual repair required'}"
            )
        if status == "NOT_READY":
            self._trigger_self_healing_sync()
            raise LanceDBNotReadyError("LanceDB index is not ready / syncing — please wait")

        return True

    def search_lancedb_parent_child(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[SearchResult], Dict[str, Any]]:
        """
        Search using the backend LanceDB parent-child engine.

        Returns:
            Tuple of (results, diagnostics)
        """
        top_k = top_k if top_k is not None else self.config.retrieval.top_k
        spill_ratio = self.config.retrieval.lancedb_child_parent_spill_ratio

        logger.info(f"LanceDB parent-child search for: '{query}' (top_k={top_k}, spill_ratio={spill_ratio})")

        start_time = time.perf_counter()

        # 1. Generate query embedding using standard embedding service
        query_embedding = self.embedding_service.encode(query)

        # 2. Call the LanceDB adapter
        from services import get_lancedb_adapter
        adapter = get_lancedb_adapter()

        raw_results = adapter.search_parent_child(
            query_text=query,
            query_vector=query_embedding,
            parent_limit=max(5, top_k),
            child_limit=top_k,
            child_parent_spill_ratio=spill_ratio,
            filters=filters
        )

        # 3. Convert to SearchResult objects
        results = []
        for i, row in enumerate(raw_results, 1):
            relevance_score = max(0.0, min(1.0, 1.0 - row["distance"]))

            results.append(SearchResult(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                text_content=row["text_content"],
                source_uri=row["source_uri"],
                distance=row["distance"],
                relevance_score=relevance_score,
                rank_score=relevance_score,
                metadata=row.get("metadata"),
                document_type=row.get("metadata", {}).get("type")
            ))

        latency_ms = (time.perf_counter() - start_time) * 1000

        diagnostics = {
            "lancedb_parent_child": {
                "active": True,
                "top_k": top_k,
                "child_parent_spill_ratio": spill_ratio,
                "latency_ms": round(latency_ms, 2),
                "matched_count": len(results),
            }
        }

        return results, diagnostics

    def _calculate_relevance_score(self, distance: float, metric: str = 'cosine') -> float:
        """
        Convert distance to relevance score (0-1, higher is better).

        Args:
            distance: Distance value from database
            metric: Distance metric used

        Returns:
            Relevance score between 0 and 1
        """
        if metric == 'cosine':
            # Cosine distance is 1 - cosine_similarity
            # So similarity = 1 - distance
            return max(0.0, min(1.0, 1.0 - distance))
        elif metric == 'l2':
            # Convert L2 distance to similarity (inverse relationship)
            # Use exponential decay
            return max(0.0, min(1.0, 1.0 / (1.0 + distance)))
        else:
            # Default: assume lower distance is better
            return max(0.0, min(1.0, 1.0 / (1.0 + distance)))

    def _build_filtered_docs_context(
        self,
        filters: Optional[Dict[str, Any]],
    ) -> Tuple[str, str, List[Any]]:
        """Build a filtered document_chunks CTE shared by hybrid search variants."""
        filter_clauses = []
        filter_params: List[Any] = []
        if filters:
            for key, value in filters.items():
                if key == 'extensions' and isinstance(value, list) and value:
                    ext_clauses = []
                    for ext in value:
                        normalized = ext if ext.startswith('.') else f'.{ext}'
                        ext_clauses.append("source_uri ILIKE %s")
                        filter_params.append(f'%{normalized}')
                    filter_clauses.append(f"({' OR '.join(ext_clauses)})")
                elif key in ['type', 'namespace', 'category']:
                    filter_clauses.append(f"metadata->>'{key}' ILIKE %s")
                    filter_params.append(value)
                elif key.startswith('metadata.'):
                    filter_clauses.append("metadata->>%s = %s")
                    filter_params.extend([key[9:], value])
                elif key in ['document_id', 'source_uri']:
                    filter_clauses.append(f"{key} = %s")
                    filter_params.append(value)
                else:
                    raise ValueError(
                        f"Unsupported filter key '{key}' for hybrid search. "
                        f"Supported keys: extensions, type, namespace, category, "
                        f"document_id, source_uri, metadata.<key>"
                    )

        if not filter_clauses:
            return "", "document_chunks", filter_params

        filter_where_sql = f"WHERE {' AND '.join(filter_clauses)}"
        filtered_docs_cte = f"""filtered_docs AS (
            SELECT
                chunk_id,
                document_id,
                chunk_index,
                text_content,
                source_uri,
                embedding,
                metadata
            FROM document_chunks
            {filter_where_sql}
        )"""
        return filtered_docs_cte, "filtered_docs", filter_params

    def search_hybrid_fusion_v0(
        self,
        query: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[SearchResult], Dict[str, Any]]:
        """Experimental dense + lexical rank fusion search."""
        top_k = top_k or self.config.retrieval.top_k
        distance_metric = self.config.retrieval.distance_metric
        dense_weight = FUSION_V0_DENSE_WEIGHT
        lexical_weight = FUSION_V0_LEXICAL_WEIGHT
        if alpha is not None:
            dense_weight = alpha
            lexical_weight = 1.0 - alpha

        phrases, terms = parse_search_query(query)
        lexical_terms = normalize_lexical_terms([*phrases, *terms] or [query])
        term_patterns = {
            term: build_exact_token_regex(term)
            for term in lexical_terms
        }
        phrase_patterns = [f"%{phrase}%" for phrase in phrases if phrase.strip()]
        dense_limit = min(max(top_k * 50, 500), 5000)
        lexical_limit = min(max(top_k * 50, 500), 5000)
        query_embedding = self.embedding_service.encode(query)
        filtered_docs_cte, candidate_source, filter_params = self._build_filtered_docs_context(filters)
        cte_prefix = f"{filtered_docs_cte}," if filtered_docs_cte else ""
        standalone_cte = f"WITH {filtered_docs_cte}" if filtered_docs_cte else ""

        dense_sql = f"""
        WITH {cte_prefix}
        dense AS (
            SELECT
                chunk_id,
                embedding <=> %s::vector AS vector_distance
            FROM {candidate_source}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        )
        SELECT
            chunk_id,
            ROW_NUMBER() OVER (ORDER BY vector_distance) AS dense_rank,
            vector_distance
        FROM dense
        ORDER BY dense_rank
        """

        total_sql = f"""
        {standalone_cte}
        SELECT COUNT(DISTINCT source_uri) AS total_documents
        FROM {candidate_source}
        """

        df_sql = f"""
        {standalone_cte}
        SELECT COUNT(DISTINCT source_uri) AS document_frequency
        FROM {candidate_source}
        WHERE text_content ~* %s
        """

        dense_rows: List[Dict[str, Any]]
        lexical_rows: List[Dict[str, Any]] = []
        term_stats: List[Dict[str, Any]] = []
        with self.db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(
                dense_sql,
                [*filter_params, query_embedding, query_embedding, dense_limit],
            )
            dense_rows = list(cursor.fetchall())

            cursor.execute(total_sql, filter_params)
            total_row = cursor.fetchone() or {}
            total_documents = int(total_row.get("total_documents") or 0)

            idf_by_term: Dict[str, float] = {}
            # TODO: Batch these term-level IDF queries to avoid N+1 database round-trips (e.g. using a single CASE WHEN query or lateral join)
            for term, pattern in term_patterns.items():
                cursor.execute(df_sql, [*filter_params, pattern])
                df_row = cursor.fetchone() or {}
                document_frequency = int(df_row.get("document_frequency") or 0)
                idf = calculate_idf(total_documents, document_frequency)
                idf_by_term[term] = idf
                term_stats.append({
                    "term": term,
                    "df": document_frequency,
                    "idf": idf,
                })

            if term_patterns or phrase_patterns:
                score_parts = []
                count_parts = []
                term_array_parts = []
                phrase_count_parts = []
                lexical_where_parts = []
                score_params: List[Any] = []
                count_params: List[Any] = []
                term_array_params: List[Any] = []
                phrase_count_params: List[Any] = []

                for term, pattern in term_patterns.items():
                    score_parts.append("CASE WHEN text_content ~* %s THEN %s ELSE 0 END")
                    score_params.extend([pattern, idf_by_term[term]])
                    count_parts.append("CASE WHEN text_content ~* %s THEN 1 ELSE 0 END")
                    count_params.append(pattern)
                    term_array_parts.append("CASE WHEN text_content ~* %s THEN %s::text ELSE NULL END")
                    term_array_params.extend([pattern, term])
                    lexical_where_parts.append("text_content ~* %s")

                for pattern in phrase_patterns:
                    phrase_count_parts.append("CASE WHEN text_content ILIKE %s THEN 1 ELSE 0 END")
                    phrase_count_params.append(pattern)
                    lexical_where_parts.append("text_content ILIKE %s")

                where_params = [*term_patterns.values(), *phrase_patterns]
                matched_idf_sql = " + ".join(score_parts) if score_parts else "0.0"
                matched_count_sql = " + ".join(count_parts) if count_parts else "0"
                matched_terms_sql = (
                    f"ARRAY_REMOVE(ARRAY[{', '.join(term_array_parts)}], NULL)"
                    if term_array_parts else "ARRAY[]::text[]"
                )
                phrase_count_sql = " + ".join(phrase_count_parts) if phrase_count_parts else "0"
                lexical_where_sql = " OR ".join(lexical_where_parts)
                full_term_match_sql = (
                    f"matched_term_count = {len(lexical_terms)}"
                    if lexical_terms else "FALSE"
                )

                lexical_sql = f"""
                WITH {cte_prefix}
                scored AS (
                    SELECT
                        chunk_id,
                        source_uri,
                        chunk_index,
                        ({matched_idf_sql})::float AS matched_idf_sum,
                        ({matched_count_sql})::int AS matched_term_count,
                        {matched_terms_sql} AS matched_terms,
                        ({phrase_count_sql})::int AS phrase_match_count
                    FROM {candidate_source}
                    WHERE {lexical_where_sql}
                ),
                ranked AS (
                    SELECT
                        *,
                        {full_term_match_sql} AS full_term_match,
                        (matched_idf_sum + (2.0 * phrase_match_count))::float AS lexical_score
                    FROM scored
                )
                SELECT
                    chunk_id,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            full_term_match DESC,
                            lexical_score DESC,
                            matched_term_count DESC,
                            source_uri ASC,
                            chunk_index ASC
                    ) AS lexical_rank,
                    lexical_score,
                    matched_terms,
                    full_term_match,
                    matched_term_count,
                    phrase_match_count
                FROM ranked
                ORDER BY lexical_rank
                LIMIT %s
                """
                cursor.execute(
                    lexical_sql,
                    [
                        *filter_params,
                        *score_params,
                        *count_params,
                        *term_array_params,
                        *phrase_count_params,
                        *where_params,
                        lexical_limit,
                    ],
                )
                lexical_rows = list(cursor.fetchall())

            dense_ranks = {
                int(row["chunk_id"]): int(row["dense_rank"])
                for row in dense_rows
            }
            lexical_ranks = {
                int(row["chunk_id"]): int(row["lexical_rank"])
                for row in lexical_rows
            }
            fused = fuse_ranked_candidates(
                dense_ranks,
                lexical_ranks,
                rrf_k=FUSION_V0_RRF_K,
                dense_weight=dense_weight,
                lexical_weight=lexical_weight,
            )[:top_k]

            if not fused:
                diagnostics = {
                    "hybrid_fusion_v0": {
                        "active": True,
                        "rrf_k": FUSION_V0_RRF_K,
                        "dense_weight": dense_weight,
                        "lexical_weight": lexical_weight,
                        "dense_limit": dense_limit,
                        "lexical_limit": lexical_limit,
                        "query_terms": term_stats,
                        "top_explanations": [],
                    }
                }
                return [], diagnostics

            fused_scores = {chunk_id: score for chunk_id, score in fused}
            chunk_ids = [chunk_id for chunk_id, _score in fused]
            hydrate_sql = """
            SELECT
                chunk_id,
                document_id,
                chunk_index,
                text_content,
                source_uri,
                embedding <=> %s::vector AS vector_distance,
                metadata
            FROM document_chunks
            WHERE chunk_id = ANY(%s)
            """
            cursor.execute(hydrate_sql, [query_embedding, chunk_ids])
            hydrated_rows = {
                int(row["chunk_id"]): row
                for row in cursor.fetchall()
            }

        dense_details = {int(row["chunk_id"]): row for row in dense_rows}
        lexical_details = {int(row["chunk_id"]): row for row in lexical_rows}
        results: List[SearchResult] = []
        top_explanations: List[Dict[str, Any]] = []
        for chunk_id, fusion_score in fused:
            row = hydrated_rows.get(chunk_id)
            if row is None:
                continue
            vector_distance = float(row["vector_distance"])
            lexical_detail = lexical_details.get(chunk_id, {})
            result = SearchResult(
                chunk_id=chunk_id,
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                text_content=row["text_content"],
                source_uri=row["source_uri"],
                distance=vector_distance,
                relevance_score=self._calculate_relevance_score(vector_distance, distance_metric),
                rank_score=fusion_score,
                metadata=row.get("metadata"),
                document_type=(row.get("metadata") or {}).get("type"),
            )
            results.append(result)
            top_explanations.append({
                "source_uri": row["source_uri"],
                "chunk_index": row["chunk_index"],
                "dense_rank": dense_details.get(chunk_id, {}).get("dense_rank"),
                "lexical_rank": lexical_detail.get("lexical_rank"),
                "matched_terms": list(lexical_detail.get("matched_terms") or []),
                "full_term_match": bool(lexical_detail.get("full_term_match", False)),
                "lexical_score": lexical_detail.get("lexical_score"),
                "fusion_score": fused_scores[chunk_id],
            })

        diagnostics = {
            "hybrid_fusion_v0": {
                "active": True,
                "rrf_k": FUSION_V0_RRF_K,
                "dense_weight": dense_weight,
                "lexical_weight": lexical_weight,
                "dense_limit": dense_limit,
                "lexical_limit": lexical_limit,
                "query_terms": term_stats,
                "top_explanations": top_explanations[:20],
            }
        }
        logger.info(f"Found {len(results)} relevant chunks (hybrid fusion v0)")
        return results, diagnostics

    def _get_reranker_v0(self):
        """Load and cache the experimental cross-encoder reranker."""
        reranker = getattr(self, "_reranker_v0", None)
        if reranker is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise ValueError(
                    "hybrid_mode rerank-v0 requires sentence-transformers to be installed"
                ) from exc
            reranker = CrossEncoder(RERANK_V0_MODEL_NAME)
            self._reranker_v0 = reranker
        return reranker

    def search_hybrid_rerank_v0(
        self,
        query: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[SearchResult], Dict[str, Any]]:
        """Experimental legacy-hybrid candidate retrieval followed by cross-encoder reranking."""
        top_k = top_k or self.config.retrieval.top_k
        candidate_limit = rerank_v0_candidate_limit(top_k)

        retrieval_start = time.perf_counter()
        candidates = self.search_hybrid(
            query=query,
            top_k=candidate_limit,
            alpha=alpha,
            filters=filters,
        )
        retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000

        diagnostics: Dict[str, Any] = {
            "rerank_v0": {
                "active": True,
                "model_name": RERANK_V0_MODEL_NAME,
                "candidate_source": "legacy_hybrid",
                "requested_top_k": top_k,
                "candidate_limit": candidate_limit,
                "candidate_count": len(candidates),
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "rerank_latency_ms": 0.0,
                "top_explanations": [],
            }
        }
        if not candidates:
            return [], diagnostics

        rerank_start = time.perf_counter()
        reranker = self._get_reranker_v0()
        raw_scores = reranker.predict([
            (query, candidate.text_content or "")
            for candidate in candidates
        ])
        rerank_scores = coerce_rerank_scores(raw_scores, len(candidates))
        rerank_latency_ms = (time.perf_counter() - rerank_start) * 1000

        ranked_candidates = sorted(
            [
                (index, candidate, rerank_scores[index])
                for index, candidate in enumerate(candidates)
            ],
            key=lambda item: (-item[2], item[0]),
        )

        results: List[SearchResult] = []
        top_explanations: List[Dict[str, Any]] = []
        for original_index, candidate, rerank_score in ranked_candidates[:top_k]:
            results.append(replace(candidate, rank_score=rerank_score))
            top_explanations.append({
                "source_uri": candidate.source_uri,
                "chunk_index": candidate.chunk_index,
                "original_rank": original_index + 1,
                "original_rank_score": candidate.rank_score,
                "rerank_score": rerank_score,
            })

        diagnostics["rerank_v0"].update({
            "rerank_latency_ms": round(rerank_latency_ms, 2),
            "returned_count": len(results),
            "top_explanations": top_explanations[:20],
        })
        logger.info(f"Found {len(results)} relevant chunks (hybrid rerank v0)")
        return results, diagnostics

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        min_score: Optional[float] = None,
        source: str = "lancedb"
    ) -> List[SearchResult]:
        """
        Search for relevant document chunks.

        Args:
            query: Search query text
            top_k: Number of results to return (uses config default if None)
            filters: Optional filters (e.g., {'document_id': 'abc123'})
            min_score: Minimum relevance score (0-1)
            source: Search backend override ('lancedb' or 'postgres')

        Returns:
            List of SearchResult objects
        """
        if self._should_use_lancedb(source):
            # Note: We intentionally ignore min_score / similarity_threshold in the LanceDB path.
            # LanceDB parent-child search utilizes FTS-staged parent retrieval, which means relevant
            # documents can have low or negative vector similarity scores in their child chunks.
            # Applying a similarity threshold would filter out valid FTS-selected results.
            results, _ = self.search_lancedb_parent_child(query, top_k, filters)
            return results

        # Use config defaults if not specified
        top_k = top_k if top_k is not None else self.config.retrieval.top_k
        min_score = min_score if min_score is not None else self.config.retrieval.similarity_threshold
        distance_metric = self.config.retrieval.distance_metric

        logger.info(f"Searching for: '{query}' (top_k={top_k}, metric={distance_metric})")

        # Generate query embedding
        query_embedding = self.embedding_service.encode(query)

        # Perform vector search
        raw_results = self.repository.search_similar(
            query_embedding=query_embedding,
            top_k=top_k * 2,  # Get more results for filtering
            distance_metric=distance_metric,
            filters=filters
        )

        # Convert to SearchResult objects with relevance scores
        results = []
        for result in raw_results:
            relevance_score = self._calculate_relevance_score(
                result['distance'],
                distance_metric
            )

            # Filter by minimum score
            if relevance_score >= min_score:
                results.append(SearchResult(
                    chunk_id=result['chunk_id'],
                    document_id=result['document_id'],
                    chunk_index=result['chunk_index'],
                    text_content=result['text_content'],
                    source_uri=result['source_uri'],
                    distance=result['distance'],
                    relevance_score=relevance_score,
                    rank_score=relevance_score,
                    metadata=result.get('metadata'),
                    document_type=result.get('metadata', {}).get('type')
                ))

        # Limit to top_k after filtering
        results = results[:top_k]

        logger.info(f"Found {len(results)} relevant chunks")
        return results

    def search_hybrid(
        self,
        query: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        source: str = "lancedb"
    ) -> List[SearchResult]:
        """
        Hybrid search combining vector and full-text search.

        Supports exact phrase matching with quoted phrases:
        - "exact phrase" or 'exact phrase' will match those words adjacent
        - Unquoted words use standard full-text search

        Args:
            query: Search query text (can include quoted phrases)
            top_k: Number of results to return
            alpha: Weight for vector search (0=full-text only, 1=vector only)
            source: Search backend override ('lancedb' or 'postgres')

        Returns:
            List of SearchResult objects
        """
        if self._should_use_lancedb(source):
            results, _ = self.search_lancedb_parent_child(query, top_k, filters)
            return results

        top_k = top_k or self.config.retrieval.top_k
        alpha = alpha if alpha is not None else self.config.retrieval.hybrid_alpha

        # Build a pre-filter CTE so both the vector and fulltext candidate branches
        # are constrained before the LIMIT, preventing missing results in large indexes.
        # Column names are plain (no table alias) because they reference document_chunks directly.
        filter_clauses = []
        filter_params: List[Any] = []
        if filters:
            for key, value in filters.items():
                if key == 'extensions' and isinstance(value, list) and value:
                    ext_clauses = []
                    for ext in value:
                        normalized = ext if ext.startswith('.') else f'.{ext}'
                        ext_clauses.append("source_uri ILIKE %s")
                        filter_params.append(f'%{normalized}')
                    filter_clauses.append(f"({' OR '.join(ext_clauses)})")
                elif key in ['type', 'namespace', 'category']:
                    filter_clauses.append(f"metadata->>'{key}' ILIKE %s")
                    filter_params.append(value)
                elif key.startswith('metadata.'):
                    filter_clauses.append("metadata->>%s = %s")
                    filter_params.extend([key[9:], value])
                elif key in ['document_id', 'source_uri']:
                    filter_clauses.append(f"{key} = %s")
                    filter_params.append(value)
                else:
                    raise ValueError(
                        f"Unsupported filter key '{key}' for hybrid search. "
                        f"Supported keys: extensions, type, namespace, category, "
                        f"document_id, source_uri, metadata.<key>"
                    )

        if filter_clauses:
            filter_where_sql = f"WHERE {' AND '.join(filter_clauses)}"
            filtered_docs_cte = f"""filtered_docs AS (
                SELECT chunk_id, embedding, text_content
                FROM document_chunks
                {filter_where_sql}
            ),"""
            candidate_source = "filtered_docs"
        else:
            filtered_docs_cte = ""
            candidate_source = "document_chunks"

        # Parse query for quoted phrases and regular terms
        phrases, terms = parse_search_query(query)

        logger.info(f"Hybrid search for: '{query}' (alpha={alpha}, phrases={phrases}, terms={terms})")

        # Generate query embedding for vector search
        query_embedding = self.embedding_service.encode(query)

        # Build the full-text search query dynamically
        # We need to combine:
        # - phraseto_tsquery for each quoted phrase (words must be adjacent)
        # - plainto_tsquery for remaining unquoted terms
        tsquery_parts = []
        tsquery_params = []

        # Add phrase queries (exact phrase matching)
        for phrase in phrases:
            tsquery_parts.append("phraseto_tsquery('english', %s)")
            tsquery_params.append(phrase)

        # Add regular term query if there are unquoted terms
        if terms:
            remaining_text = ' '.join(terms)
            tsquery_parts.append("plainto_tsquery('english', %s)")
            tsquery_params.append(remaining_text)

        # If no search terms at all, fall back to empty query (matches nothing in full-text)
        if not tsquery_parts:
            # Use the original query as-is for plainto_tsquery
            tsquery_expression = "plainto_tsquery('english', %s)"
            tsquery_params = [query]
        else:
            # Combine all parts with AND operator (&&)
            tsquery_expression = ' && '.join(tsquery_parts)

        # PostgreSQL full-text search can miss short model codes / identifiers
        # such as "EV6". Add a literal substring fallback so exact text hits are
        # candidates and receive the text-match boost.
        literal_tokens = [token.strip() for token in [*phrases, *terms] if token.strip()]
        if not literal_tokens and query.strip():
            literal_tokens = [query.strip()]
        lexical_expression = (
            " AND ".join(["text_content ILIKE %s" for _ in literal_tokens])
            if literal_tokens else "FALSE"
        )
        scored_lexical_expression = (
            " AND ".join(["d.text_content ILIKE %s" for _ in literal_tokens])
            if literal_tokens else "FALSE"
        )
        lexical_params = [f"%{token}%" for token in literal_tokens]

        # Build the full SQL query
        # Strategy: Get candidates from BOTH vector and fulltext search via UNION,
        # then compute combined scores. This ensures exact text matches are never lost.
        candidate_limit = max(top_k * 100, 1000)  # At least 1000, or 100x top_k

        query_sql = f"""
        WITH {filtered_docs_cte}
        candidates AS (
            -- Top vector search results constrained to filtered source
            SELECT chunk_id FROM (
                SELECT chunk_id FROM {candidate_source}
                ORDER BY embedding <=> %s::vector
                LIMIT {candidate_limit}
            ) AS vector_candidates
            UNION
            -- All fulltext matches from the same filtered source
            SELECT chunk_id FROM {candidate_source}
            WHERE to_tsvector('english', text_content) @@ ({tsquery_expression})
            UNION
            -- Literal substring matches for short identifiers (e.g. EV6)
            SELECT chunk_id FROM {candidate_source}
            WHERE {lexical_expression}
        ),
        scored AS (
            SELECT
                c.chunk_id,
                d.document_id,
                d.chunk_index,
                d.text_content,
                d.source_uri,
                d.embedding <=> %s::vector AS vector_distance,
                ROW_NUMBER() OVER (ORDER BY d.embedding <=> %s::vector) AS vector_rank,
                CASE
                    WHEN to_tsvector('english', d.text_content) @@ ({tsquery_expression})
                    THEN ts_rank_cd(to_tsvector('english', d.text_content), {tsquery_expression})
                    WHEN {scored_lexical_expression}
                    THEN 1.0
                    ELSE 0
                END AS text_score,
                CASE
                    WHEN to_tsvector('english', d.text_content) @@ ({tsquery_expression})
                        OR ({scored_lexical_expression})
                    THEN 1
                    ELSE 0
                END AS has_text_match
            FROM candidates c
            JOIN document_chunks d ON c.chunk_id = d.chunk_id
        ),
        ranked AS (
            SELECT *,
                -- Compute text rank among those with text matches (DENSE_RANK to handle ties)
                CASE WHEN has_text_match = 1
                    THEN DENSE_RANK() OVER (
                        PARTITION BY has_text_match
                        ORDER BY text_score DESC
                    )
                    ELSE NULL
                END AS text_rank
            FROM scored
        )
        SELECT
            chunk_id,
            document_id,
            chunk_index,
            text_content,
            source_uri,
            vector_distance,
            text_score,
            -- Reciprocal Rank Fusion: boost text matches with 10.0, use 1/rank for both
            CASE WHEN has_text_match = 1
                THEN 10.0 + (%s * (1.0 / NULLIF(vector_rank, 0)) + %s * (1.0 / NULLIF(text_rank, 0)))
                ELSE %s * (1.0 / NULLIF(vector_rank, 0))
            END AS combined_score
        FROM ranked
        ORDER BY combined_score DESC
        LIMIT %s
        """

        # Build parameter list in SQL text order (left-to-right):
        # filtered_docs CTE WHERE: filter_params (only present when filters active)
        # candidates CTE: embedding (ORDER BY), tsquery_params (fulltext WHERE),
        #   then lexical_params (literal WHERE)
        # scored CTE: embedding x2 (vector_distance, ROW_NUMBER), then
        #   tsquery/lexical params in the order text_score and has_text_match use them
        # final SELECT: alpha x3, top_k
        params = list(filter_params)    # filtered_docs WHERE (empty when no filters)
        params.append(query_embedding)  # candidates ORDER BY
        params.extend(tsquery_params)   # candidates fulltext WHERE
        params.extend(lexical_params)   # candidates literal WHERE
        params.extend([query_embedding, query_embedding])  # scored: distance, ROW_NUMBER
        params.extend(tsquery_params)   # scored text_score: fulltext WHEN
        params.extend(tsquery_params)   # scored text_score: ts_rank_cd
        params.extend(lexical_params)   # scored text_score: literal WHEN
        params.extend(tsquery_params)   # scored has_text_match: fulltext WHEN
        params.extend(lexical_params)   # scored has_text_match: literal OR
        params.extend([alpha, 1 - alpha, alpha, top_k])

        with self.db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute(query_sql, params)
            raw_results = cursor.fetchall()

        # Convert to SearchResult objects
        results = []
        for result in raw_results:
            relevance_score = self._calculate_relevance_score(
                result['vector_distance'],
                self.config.retrieval.distance_metric
            )

            results.append(SearchResult(
                chunk_id=result['chunk_id'],
                document_id=result['document_id'],
                chunk_index=result['chunk_index'],
                text_content=result['text_content'],
                source_uri=result['source_uri'],
                distance=result['vector_distance'],
                relevance_score=relevance_score,
                rank_score=float(result['combined_score'])
            ))

        logger.info(f"Found {len(results)} relevant chunks (hybrid)")
        return results

    def get_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        use_hybrid: bool = False,
        source: str = "lancedb"
    ) -> str:
        """
        Get concatenated context from search results for RAG.

        Args:
            query: Search query
            top_k: Number of results
            use_hybrid: Use hybrid search
            source: Search backend override ('lancedb' or 'postgres')

        Returns:
            Concatenated context string
        """
        if use_hybrid and self.config.retrieval.enable_hybrid_search:
            results = self.search_hybrid(query, top_k, source=source)
        else:
            results = self.search(query, top_k, source=source)

        if not results:
            return ""

        # Build context with source attribution
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[Source {i}: {result.source_uri}, Chunk {result.chunk_index}]\n"
                f"{result.text_content}\n"
            )

        return "\n".join(context_parts)


def format_results(results: List[SearchResult], verbose: bool = False) -> str:
    """
    Format search results for display.

    Args:
        results: List of SearchResult objects
        verbose: Show full text if True

    Returns:
        Formatted string
    """
    if not results:
        return "\nNo relevant results found."

    output = [f"\nFound {len(results)} relevant results:\n"]
    output.append("=" * 80)

    for i, result in enumerate(results, 1):
        output.append(f"\n[Result {i}]")
        output.append(f"Relevance Score: {result.relevance_score:.4f}")
        output.append(f"Source: {result.source_uri}")
        output.append(f"Chunk: #{result.chunk_index}")
        output.append(f"Distance: {result.distance:.4f}")

        if verbose:
            output.append(f"\nFull Text:\n{result.text_content}")
        else:
            preview = result.text_content[:300].replace('\n', ' ')
            output.append(f"\nPreview: {preview}...")

        output.append("-" * 80)

    return "\n".join(output)


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description='PGVectorRAGIndexer v2 - Search indexed documents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search
  python retriever_v2.py "What is machine learning?"

  # Search with custom top_k
  python retriever_v2.py "Python programming" --top-k 10

  # Hybrid search (vector + full-text)
  python retriever_v2.py "database optimization" --hybrid

  # Search with minimum score threshold
  python retriever_v2.py "neural networks" --min-score 0.8

  # Verbose output (show full text)
  python retriever_v2.py "data science" --verbose

  # Get context for RAG
  python retriever_v2.py "explain transformers" --context
        """
    )

    parser.add_argument(
        'query',
        type=str,
        help='Search query text'
    )
    parser.add_argument(
        '--top-k',
        type=int,
        help='Number of results to return (default: from config)'
    )
    parser.add_argument(
        '--min-score',
        type=float,
        help='Minimum relevance score 0-1 (default: from config)'
    )
    parser.add_argument(
        '--hybrid',
        action='store_true',
        help='Use hybrid search (vector + full-text)'
    )
    parser.add_argument(
        '--alpha',
        type=float,
        help='Hybrid search weight for vector search (0-1, default: 0.5)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show full text of results'
    )
    parser.add_argument(
        '--context',
        action='store_true',
        help='Output as concatenated context for RAG'
    )
    parser.add_argument(
        '--filter-doc',
        type=str,
        help='Filter by document ID'
    )

    args = parser.parse_args()

    # Initialize retriever
    try:
        retriever = DocumentRetriever()
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
        sys.exit(1)

    # Execute search
    try:
        # Build filters
        filters = {}
        if args.filter_doc:
            filters['document_id'] = args.filter_doc

        # Perform search
        if args.context:
            # Get context for RAG
            context = retriever.get_context(
                args.query,
                top_k=args.top_k,
                use_hybrid=args.hybrid
            )
            print(context)
        else:
            # Regular search
            if args.hybrid:
                results = retriever.search_hybrid(
                    args.query,
                    top_k=args.top_k,
                    alpha=args.alpha
                )
            else:
                results = retriever.search(
                    args.query,
                    top_k=args.top_k,
                    filters=filters if filters else None,
                    min_score=args.min_score
                )

            # Display results
            output = format_results(results, verbose=args.verbose)
            print(output)

    except KeyboardInterrupt:
        print("\n\nSearch cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
