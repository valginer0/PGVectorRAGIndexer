"""Local LanceDB retrieval engine for the desktop V2 search path.

The engine is intentionally UI-free and API-free. It indexes local document
texts into an embedded LanceDB folder, then searches with a two-tier retrieval
shape: parent-document FTS first, child-chunk vector search second.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence


PARENT_TABLE = "parent_documents"
CHUNK_TABLE = "document_chunks"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384
VECTOR_METRIC = "cosine"
MIN_VECTOR_INDEX_ROWS = 256
# A parent ranked below the top parent contributes child chunks only if its
# document-level FTS score is at least this fraction of the top parent's score.
# 1.0 means "top parent only" except exact ties; lower values allow multi-document
# spill at the cost of precision on corpora with thin parent-score margins. We gate
# spill on parent FTS (the reliable "is this the right document" signal), not on
# child vector similarity, because for exact-identifier queries the correct (often
# terse) document scores LOWER on vector similarity than chatty unrelated prose.
DEFAULT_CHILD_PARENT_SPILL_RATIO = 0.7

LOGGER = logging.getLogger(__name__)


class LanceDBEngineError(RuntimeError):
    """Base class for local LanceDB engine failures."""


class LanceDBDependencyError(LanceDBEngineError):
    """Raised when optional LanceDB desktop dependencies are unavailable."""


class EmbeddingModelError(LanceDBEngineError):
    """Raised when embeddings cannot be produced safely."""


class Embedder(Protocol):
    """Small interface for embedding providers."""

    @property
    def dimension(self) -> int:
        ...

    def encode(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class LocalDocument:
    """A local document ready for LanceDB ingestion."""

    source_uri: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    rank: int
    chunk_id: int
    source_uri: str
    chunk_index: int
    text: str
    score: float
    score_label: str
    parent_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "source_uri": self.source_uri,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "score": self.score,
            "score_label": self.score_label,
            "parent_rank": self.parent_rank,
        }


@dataclass(frozen=True)
class SearchTelemetry:
    query_type: str
    total_time_ms: float
    fts_time_ms: float = 0.0
    vector_time_ms: float = 0.0
    matched_parents: list[str] = field(default_factory=list)
    matched_parent_details: list[dict[str, Any]] = field(default_factory=list)
    filter_clause: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type,
            "total_time_ms": self.total_time_ms,
            "fts_time_ms": self.fts_time_ms,
            "vector_time_ms": self.vector_time_ms,
            "matched_parents": self.matched_parents,
            "matched_parent_details": self.matched_parent_details,
            "filter_clause": self.filter_clause,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class IngestionStats:
    source_count: int
    chunk_count: int
    db_path: str


class SentenceTransformerEmbedder:
    """Sentence-transformers embedder that fails closed on bad vectors."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        cache_folder: str | None = None,
        expected_dimension: int = DEFAULT_EMBEDDING_DIM,
    ):
        self.model_name = model_name
        self._dimension = expected_dimension
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name, cache_folder=cache_folder)
        except Exception as exc:  # pragma: no cover - exercised in packaging gate
            raise EmbeddingModelError(
                f"Could not load sentence-transformers model {model_name!r}: {exc}"
            ) from exc

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, text: str) -> list[float]:
        try:
            vector = self._model.encode(text or "")
        except Exception as exc:  # pragma: no cover - exercised in packaging gate
            raise EmbeddingModelError(f"Could not encode text: {exc}") from exc

        values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
        return _validate_embedding(values, self._dimension)


class HashingEmbedder:
    """Small deterministic embedder for tests and offline smoke checks.

    This is not intended for production ranking quality. It is useful for tests
    because it produces stable non-zero vectors without downloading a model.
    """

    def __init__(self, dimension: int = 32):
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", (text or "").lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self._dimension
            vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return _validate_embedding(vector, self._dimension)


class LocalLanceDBEngine:
    """Embedded LanceDB engine for local desktop search."""

    # Cap of chunks per parent document to prevent a single document from monopolizing search results.
    # Preserves precision-first ordering while ensuring diversity across documents.
    MAX_CHUNKS_PER_PARENT = 3

    def __init__(self, db_path: str | Path, *, embedder: Embedder | None = None):
        self.db_path = Path(db_path)
        self.embedder = embedder or SentenceTransformerEmbedder()
        self._lancedb, self._pa = _load_lancedb_dependencies()
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = self._lancedb.connect(str(self.db_path))
        self._closed = False

    def __enter__(self) -> "LocalLanceDBEngine":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the LanceDB connection if the installed version exposes close()."""
        if self._closed:
            return
        db = self.db
        close = getattr(db, "close", None)
        if callable(close):
            close()
        self.db = None
        self._closed = True

    @property
    def embedding_dimension(self) -> int:
        return self.embedder.dimension

    def table_names(self) -> list[str]:
        self._ensure_open()
        if hasattr(self.db, "list_tables"):
            tables = self.db.list_tables()
            if hasattr(tables, "tables"):
                return list(tables.tables)
            if isinstance(tables, dict):
                return list(tables.get("tables", []))
            return list(tables)
        return list(self.db.table_names())

    def is_indexed(self) -> bool:
        tables = set(self.table_names())
        return PARENT_TABLE in tables and CHUNK_TABLE in tables

    def ingest_documents(
        self,
        documents: Sequence[LocalDocument],
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 120,
        mode: str = "overwrite",
    ) -> IngestionStats:
        """Ingest local document text into parent and child LanceDB tables."""
        self._ensure_open()
        if not documents:
            raise ValueError("documents must not be empty")
        if mode != "overwrite":
            raise ValueError("only overwrite ingestion is supported in V2 slice 1")

        parent_rows: list[dict[str, Any]] = []
        chunk_rows: list[dict[str, Any]] = []
        next_chunk_id = 1

        for doc in documents:
            chunks = split_text(doc.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            if not chunks:
                raise ValueError(f"document text must not be empty: {doc.source_uri}")
            parent_rows.append(
                {
                    "source_uri": doc.source_uri,
                    "aggregated_text": "\n\n".join(chunks),
                    "chunk_count": len(chunks),
                }
            )
            for chunk_index, text in enumerate(chunks):
                chunk_rows.append(
                    {
                        "chunk_id": next_chunk_id,
                        "source_uri": doc.source_uri,
                        "chunk_index": chunk_index,
                        "text_content": text,
                        "embedding": self._encode(text),
                    }
                )
                next_chunk_id += 1

        parent_table = self.db.create_table(
            PARENT_TABLE,
            data=self._parent_arrow_table(parent_rows),
            mode=mode,
        )
        chunk_table = self.db.create_table(
            CHUNK_TABLE,
            data=self._chunk_arrow_table(chunk_rows),
            mode=mode,
        )
        self._create_fts_index(parent_table, "aggregated_text")
        self._create_fts_index(chunk_table, "text_content")
        self._create_vector_index(chunk_table, row_count=len(chunk_rows))
        return IngestionStats(
            source_count=len(parent_rows),
            chunk_count=len(chunk_rows),
            db_path=str(self.db_path),
        )

    def search_flat_global_hybrid(
        self,
        query: str,
        *,
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> tuple[list[SearchResult], SearchTelemetry]:
        """Compare against a flat global FTS/vector RRF search."""
        self._ensure_open()
        self._ensure_indexed()
        self._validate_search_args(query, top_k)
        start = time.perf_counter()
        chunks = self.db.open_table(CHUNK_TABLE)

        t0 = time.perf_counter()
        fts_rows = chunks.search(query, query_type="fts").limit(top_k * 2).to_arrow().to_pylist()
        fts_time = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        query_vector = self._encode(query)
        vector_rows = (
            self._vector_search(chunks, query_vector)
            .limit(top_k * 2)
            .to_arrow()
            .to_pylist()
        )
        vector_time = (time.perf_counter() - t1) * 1000

        scores: dict[int, float] = {}
        for rank, row in enumerate(fts_rows, 1):
            scores[int(row["chunk_id"])] = scores.get(int(row["chunk_id"]), 0.0) + 1.0 / (rrf_k + rank)
        for rank, row in enumerate(vector_rows, 1):
            scores[int(row["chunk_id"])] = scores.get(int(row["chunk_id"]), 0.0) + 1.0 / (rrf_k + rank)

        by_chunk_id: dict[int, dict[str, Any]] = {}
        # Vector rows win if duplicate LanceDB result metadata ever diverges.
        for row in fts_rows + vector_rows:
            by_chunk_id[int(row["chunk_id"])] = row

        ranked_rows = sorted(
            by_chunk_id.values(),
            key=lambda row: (-scores[int(row["chunk_id"])], int(row["chunk_id"])),
        )[:top_k]
        results = [
            self._result_from_row(
                row,
                rank=rank,
                score=scores[int(row["chunk_id"])],
                score_label=f"RRF: {scores[int(row['chunk_id'])]:.5f}",
            )
            for rank, row in enumerate(ranked_rows, 1)
        ]
        telemetry = SearchTelemetry(
            query_type="flat_global_hybrid_rrf",
            total_time_ms=(time.perf_counter() - start) * 1000,
            fts_time_ms=fts_time,
            vector_time_ms=vector_time,
            explanation="Global FTS and vector chunk searches blended with reciprocal rank fusion.",
        )
        return results, telemetry

    def search_parent_child(
        self,
        query: str,
        *,
        parent_limit: int = 5,
        child_limit: int = 10,
        child_parent_spill_ratio: float = DEFAULT_CHILD_PARENT_SPILL_RATIO,
    ) -> tuple[list[SearchResult], SearchTelemetry]:
        """Search parent documents with FTS, then child chunks with vector search."""
        self._ensure_open()
        self._ensure_indexed()
        self._validate_search_args(query, child_limit)
        if parent_limit <= 0:
            raise ValueError("parent_limit must be positive")
        if child_parent_spill_ratio < 0:
            raise ValueError("child_parent_spill_ratio must be non-negative")
        start = time.perf_counter()
        parents = self.db.open_table(PARENT_TABLE)
        chunks = self.db.open_table(CHUNK_TABLE)

        t0 = time.perf_counter()
        parent_rows = (
            parents.search(query, query_type="fts")
            .limit(parent_limit)
            .to_arrow()
            .to_pylist()
        )
        fts_time = (time.perf_counter() - t0) * 1000
        matched_parents = [str(row["source_uri"]) for row in parent_rows]
        matched_parent_details = [
            {
                "rank": rank,
                "source_uri": str(row["source_uri"]),
                "fts_score": float(row["_score"]) if row.get("_score") is not None else None,
            }
            for rank, row in enumerate(parent_rows, 1)
        ]
        parent_ranks = {source_uri: rank for rank, source_uri in enumerate(matched_parents, 1)}

        vector_time = 0.0
        filter_clause = None
        results: list[SearchResult] = []
        if matched_parents:
            # Telemetry keeps the full candidate-set filter for readability.
            filter_clause = self._source_uri_filter(matched_parents)
            t1 = time.perf_counter()
            query_vector = self._encode(query)
            # Parent-stratified fulfillment: run the child vector search per parent so
            # a weaker parent's chunk cannot displace the top parent's chunks in a single
            # global ranking. The top parent always contributes; a lower-ranked parent
            # contributes only if its FTS score clears child_parent_spill_ratio of the
            # top parent's score. We do NOT pad to child_limit from unqualified parents:
            # returning 1-3 confident chunks beats 5 with a decorative tail.
            top_fts = matched_parent_details[0]["fts_score"]
            spill_parents = self._spill_parents(
                matched_parent_details, top_fts, child_parent_spill_ratio
            )
            stratified_rows: list[dict[str, Any]] = []
            for source_uri in spill_parents:
                per_parent_rows = (
                    self._vector_search(chunks, query_vector)
                    .where(self._source_uri_filter([source_uri]))
                    .limit(min(child_limit, self.MAX_CHUNKS_PER_PARENT))
                    .to_arrow()
                    .to_pylist()
                )
                stratified_rows.extend(per_parent_rows)
            stratified_rows.sort(
                key=lambda row: (
                    parent_ranks.get(str(row["source_uri"]), len(parent_ranks) + 1),
                    float(row.get("_distance", 1.0)),
                )
            )
            child_rows = stratified_rows[:child_limit]
            vector_time = (time.perf_counter() - t1) * 1000
            results = [
                self._result_from_row(
                    row,
                    rank=rank,
                    score=self._cosine_similarity(row),
                    score_label=self._cosine_score_label(row),
                    parent_rank=parent_ranks.get(str(row["source_uri"])),
                )
                for rank, row in enumerate(child_rows, 1)
            ]

        telemetry = SearchTelemetry(
            query_type="parent_child",
            total_time_ms=(time.perf_counter() - start) * 1000,
            fts_time_ms=fts_time,
            vector_time_ms=vector_time,
            matched_parents=matched_parents,
            matched_parent_details=matched_parent_details,
            filter_clause=filter_clause,
            explanation=(
                "Document-level FTS selected parent documents; child vector search "
                "was run per parent (parent-stratified) and ordered by parent FTS rank, "
                "then by vector distance within each parent."
            ),
        )
        return results, telemetry

    def _ensure_open(self) -> None:
        if self._closed:
            raise LanceDBEngineError("LanceDB engine is closed")

    def _ensure_indexed(self) -> None:
        if not self.is_indexed():
            raise LanceDBEngineError("LanceDB index is not ready; ingest documents first")

    def _encode(self, text: str) -> list[float]:
        return _validate_embedding(self.embedder.encode(text), self.embedding_dimension)

    @staticmethod
    def _vector_search(table: Any, query_vector: list[float]) -> Any:
        query = table.search(query_vector, vector_column_name="embedding")
        metric = getattr(query, "metric", None)
        if callable(metric):
            query = metric(VECTOR_METRIC)
        else:  # pragma: no cover - current pinned LanceDB exposes metric()
            LOGGER.debug("LanceDB query builder has no metric(); default vector metric will be used")
        return query

    @staticmethod
    def _cosine_similarity(row: dict[str, Any]) -> float:
        return 1.0 - float(row.get("_distance", 1.0))

    @classmethod
    def _cosine_score_label(cls, row: dict[str, Any]) -> str:
        distance = float(row.get("_distance", 1.0))
        return f"Cosine similarity: {cls._cosine_similarity(row):.4f} (distance: {distance:.4f})"

    @staticmethod
    def _validate_search_args(query: str, limit: int) -> None:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if limit <= 0:
            raise ValueError("limit must be positive")

    def _parent_arrow_table(self, rows: list[dict[str, Any]]):
        pa = self._pa
        schema = pa.schema(
            [
                pa.field("source_uri", pa.string(), nullable=False),
                pa.field("aggregated_text", pa.string(), nullable=False),
                pa.field("chunk_count", pa.int32(), nullable=False),
            ]
        )
        return pa.Table.from_pylist(rows, schema=schema)

    def _chunk_arrow_table(self, rows: list[dict[str, Any]]):
        pa = self._pa
        schema = pa.schema(
            [
                pa.field("chunk_id", pa.int64(), nullable=False),
                pa.field("source_uri", pa.string(), nullable=False),
                pa.field("chunk_index", pa.int32(), nullable=False),
                pa.field("text_content", pa.string(), nullable=False),
                pa.field("embedding", pa.list_(pa.float32(), self.embedding_dimension), nullable=False),
            ]
        )
        return pa.Table.from_pylist(rows, schema=schema)

    @staticmethod
    def _create_fts_index(table: Any, column: str) -> None:
        try:
            table.create_fts_index(column, replace=True)
        except TypeError:
            table.create_fts_index(column)

    @staticmethod
    def _create_vector_index(table: Any, *, row_count: int) -> None:
        if row_count < MIN_VECTOR_INDEX_ROWS:
            return
        try:
            table.create_index(
                metric=VECTOR_METRIC,
                vector_column_name="embedding",
                replace=True,
            )
        except Exception as exc:  # pragma: no cover - index remains an optimization
            LOGGER.debug("Could not create LanceDB vector index: %s", exc)

    @staticmethod
    def _quote_lancedb_string(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _spill_parents(
        matched_parent_details: list[dict[str, Any]],
        top_fts: float | None,
        spill_ratio: float,
    ) -> list[str]:
        """Parents (in FTS rank order) allowed to contribute child chunks.

        The top parent always qualifies. A lower-ranked parent qualifies only if
        its FTS score is at least ``spill_ratio`` of the top parent's score. If the
        top FTS score is missing or non-positive we cannot judge ratios, so we fall
        back to the top parent only.
        """
        allowed: list[str] = []
        for detail in matched_parent_details:
            if detail["rank"] == 1:
                allowed.append(detail["source_uri"])
                continue
            score = detail["fts_score"]
            if (
                top_fts is not None
                and top_fts > 0
                and score is not None
                and score >= top_fts * spill_ratio
            ):
                allowed.append(detail["source_uri"])
        return allowed

    @classmethod
    def _source_uri_filter(cls, source_uris: Sequence[str]) -> str:
        quoted = ", ".join(cls._quote_lancedb_string(source_uri) for source_uri in source_uris)
        return f"source_uri IN ({quoted})"

    @staticmethod
    def _result_from_row(
        row: dict[str, Any],
        *,
        rank: int,
        score: float,
        score_label: str,
        parent_rank: int | None = None,
    ) -> SearchResult:
        return SearchResult(
            rank=rank,
            chunk_id=int(row["chunk_id"]),
            source_uri=str(row["source_uri"]),
            chunk_index=int(row["chunk_index"]),
            text=str(row["text_content"]),
            score=float(score),
            score_label=score_label,
            parent_rank=parent_rank,
        )


def split_text(text: str, *, chunk_size: int = 1200, chunk_overlap: int = 120) -> list[str]:
    """Split local document text into stable character chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    normalized = (text or "").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end].strip())
        if end == len(normalized):
            break
        start = end - chunk_overlap
    return [chunk for chunk in chunks if chunk]


def _validate_embedding(values: Sequence[float], expected_dimension: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != expected_dimension:
        raise EmbeddingModelError(
            f"embedding dimension mismatch: expected {expected_dimension}, got {len(vector)}"
        )
    if not any(value != 0.0 for value in vector):
        raise EmbeddingModelError("embedding provider returned an all-zero vector")
    return vector


def _load_lancedb_dependencies():
    try:
        import lancedb
        import pyarrow as pa
    except Exception as exc:
        raise LanceDBDependencyError(
            "Local LanceDB search requires optional desktop dependencies: lancedb and pyarrow"
        ) from exc
    return lancedb, pa
