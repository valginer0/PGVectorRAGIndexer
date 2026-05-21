#!/usr/bin/env python3
"""
LanceDB embedded sidecar comparison for RAG retrieval spike evaluation (Phase 2).

Extracts pre-computed embeddings and text from the PG17 spike database,
indexes them into a local embedded LanceDB instance, and runs EV6 benchmark
queries to compare lexical, vector, and hybrid retrieval against the PG17
partitioned-semantic baseline.

Three validation checks:
  (1) Tokenization divergence matrix: Tantivy vs PG17 simple/english dictionaries
  (2) Lexical & semantic quality for "EV6 charging" and "EV6 battery" vs PG17
  (3) Indexing and query latency benchmark for the .txt cohort (~61k chunks)

Usage:
  # First run: extract + ingest + index + query
  venv/bin/python scripts/search_lancedb_compare.py --output-json lancedb_spike.json

  # Subsequent runs: reuse existing table
  venv/bin/python scripts/search_lancedb_compare.py --skip-ingest --output-json lancedb_spike.json

Dependencies:
  venv/bin/pip install lancedb pyarrow
  venv/bin/pip install sentence-transformers  # optional, for real embeddings
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql as pgsql
from psycopg2.extras import RealDictCursor

try:
    import lancedb
    import pyarrow as pa
except ImportError as exc:
    sys.exit(
        f"ERROR: {exc}\n"
        "  Install with: venv/bin/pip install lancedb pyarrow"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_QUERIES = ["EV6 charging", "EV6 battery"]
DEFAULT_LANCE_PATH = "./lancedb_spike_data"
DEFAULT_TABLE_NAME = "document_chunks_txt"
DEFAULT_PG_DOCUMENT_TABLE = "search_spike_document_text"
DEFAULT_EXTENSION_FILTER = "txt"
EMBEDDING_DIM = 384
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Test corpus for the Tantivy tokenization diagnostic mini-table.
# Chosen to exercise alphanumeric identifiers, hyphenated codes, and common terms.
_TOKENIZATION_TEST_STRINGS = [
    "EV6 charging issue found in diagnostic report",
    "ev6 model battery voltage nominal reading",
    "EV-6 variant identified in service bulletin",
    "EV7 charging port compatibility failure",
    "charging adapter standard protocol mismatch",
    "ZXQ-000-NOT-REAL fake system identifier test",
    "12V battery load test complete pass result",
    "electric vehicle ev charging station EV 6",
]

_TOKENIZATION_QUERIES = [
    "EV6", "ev6", "EV6 charging", "EV6 battery", "EV-6", "ZXQ-000", "charging",
]


# ---------------------------------------------------------------------------
# Embedding helpers (soft dependency on sentence_transformers)
# ---------------------------------------------------------------------------

def _load_embedding_model():
    """Load the SentenceTransformer model; return None and warn on failure."""
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        print(
            f"WARNING: sentence_transformers unavailable ({exc}); "
            "using zero-vector fallback for all vector queries. "
            "Structural results are valid; quality rankings are not.",
            file=sys.stderr,
        )
        return None


def _encode(model, query: str) -> list[float]:
    """Encode a query string, or return a zero vector if the model is None."""
    if model is None:
        return [0.0] * EMBEDDING_DIM
    v = model.encode(query)
    return v.tolist() if hasattr(v, "tolist") else list(v)


# ---------------------------------------------------------------------------
# PG17 helpers
# ---------------------------------------------------------------------------

def pg_connect(args: argparse.Namespace):
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.database,
        user=args.user,
        password=args.password,
    )


def pg_extract_chunks(
    conn,
    extension_filter: str,
    limit: int | None = None,
) -> tuple[list[dict], float]:
    """
    Extract chunk_id, source_uri, chunk_index, text_content, and embedding
    from PG17 document_chunks for the given file extension. Embeddings are
    returned as PostgreSQL vector literals (text) to avoid pgvector Python
    dependency; parsed later in build_arrow_table.
    """
    limit_clause = f"LIMIT {limit}" if limit else ""
    start = time.perf_counter()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                chunk_id,
                source_uri,
                chunk_index,
                text_content,
                embedding::text AS embedding_text
            FROM document_chunks
            WHERE source_uri ILIKE %s
            ORDER BY source_uri, chunk_index
            {limit_clause}
            """,
            (f"%{extension_filter}",),
        )
        rows = [dict(r) for r in cur.fetchall()]
    wall_ms = (time.perf_counter() - start) * 1000
    return rows, wall_ms


def pg_stemming_diagnostic(conn, test_strings: list[str]) -> dict[str, Any]:
    """
    Return how PG17's 'simple' and 'english' dictionaries tokenize each string.
    Used to compare directly against Tantivy's observed behavior.
    """
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for s in test_strings:
            entry: dict[str, str] = {}
            for cfg in ("simple", "english"):
                cur.execute("SELECT to_tsvector(%s, %s)::text", (cfg, s))
                row = cur.fetchone()
                entry[cfg] = row[0] if row else ""
            out[s] = entry
    return out


def pg_partitioned_semantic_baseline(
    conn,
    *,
    document_table: str,
    query: str,
    query_embedding: list[float],
    extension_filter: str,
    parent_limit: int = 5,
    child_limit: int = 5,
) -> tuple[list[dict], float]:
    """
    Run the partitioned-semantic parent-child query on PG17 (the Spike 1 gold
    standard) for direct apples-to-apples comparison with LanceDB results.
    """
    emb_lit = "[" + ",".join(str(x) for x in query_embedding) + "]"
    q_sql = pgsql.SQL("""
        WITH top_parent_docs AS (
            SELECT
                source_uri,
                chunk_count,
                content <@> %s AS parent_bm25_score
            FROM {}
            WHERE source_uri ILIKE %s
            ORDER BY content <@> %s
            LIMIT %s
        ),
        ranked_parent_docs AS (
            SELECT
                source_uri,
                chunk_count,
                parent_bm25_score,
                ROW_NUMBER() OVER (ORDER BY parent_bm25_score, source_uri) AS parent_rank
            FROM top_parent_docs
        ),
        child_chunks AS (
            SELECT
                p.parent_rank, p.source_uri, p.chunk_count AS parent_chunk_count,
                p.parent_bm25_score, c.chunk_id, c.chunk_index, c.text_content,
                (c.embedding <=> %s::vector) AS vector_distance,
                ROW_NUMBER() OVER (
                    PARTITION BY c.source_uri
                    ORDER BY (c.embedding <=> %s::vector) ASC
                ) AS child_rank
            FROM ranked_parent_docs p
            JOIN document_chunks c ON c.source_uri = p.source_uri
        )
        SELECT
            parent_rank, source_uri, parent_chunk_count, parent_bm25_score,
            chunk_id, chunk_index, vector_distance, child_rank,
            LEFT(REPLACE(text_content, E'\\n', ' '), 220) AS preview
        FROM child_chunks
        WHERE child_rank <= %s
        ORDER BY parent_rank, child_rank
    """).format(pgsql.Identifier(document_table))

    params = [query, f"%{extension_filter}", query, parent_limit,
              emb_lit, emb_lit, child_limit]
    start = time.perf_counter()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q_sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    return rows, (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# LanceDB ingestion
# ---------------------------------------------------------------------------

def _parse_pg_vector(text: str) -> list[float]:
    """Parse a PostgreSQL vector literal '[x,y,...]' into a list of floats."""
    return [float(x) for x in text.strip("[]").split(",")]


def build_arrow_table(rows: list[dict]) -> pa.Table:
    """
    Convert PG17 extraction rows to a PyArrow table for LanceDB ingestion.
    Embeddings are parsed from PG vector text literals and stored as fixed-size
    float32 lists so LanceDB can build an efficient vector index.
    """
    print(f"  [build] Parsing {len(rows):,} embedding vectors...", file=sys.stderr)
    t0 = time.perf_counter()
    embeddings = [_parse_pg_vector(r["embedding_text"]) for r in rows]
    parse_ms = (time.perf_counter() - t0) * 1000
    print(f"  [build] Parsed in {parse_ms:.0f}ms", file=sys.stderr)

    return pa.table({
        "chunk_id": pa.array([r["chunk_id"] for r in rows], type=pa.int64()),
        "source_uri": pa.array([r["source_uri"] for r in rows], type=pa.utf8()),
        "chunk_index": pa.array([r["chunk_index"] for r in rows], type=pa.int32()),
        "text_content": pa.array([r["text_content"] or "" for r in rows], type=pa.utf8()),
        "embedding": pa.array(embeddings, type=pa.list_(pa.float32(), EMBEDDING_DIM)),
    })


def lance_ingest(
    db: lancedb.DBConnection,
    table_name: str,
    arrow_tbl: pa.Table,
) -> tuple[Any, float]:
    """Create a LanceDB table from an Arrow table, overwriting any existing one."""
    start = time.perf_counter()
    tbl = db.create_table(table_name, data=arrow_tbl, mode="overwrite")
    return tbl, (time.perf_counter() - start) * 1000


def lance_create_fts_index(tbl: Any) -> float:
    """Create a Tantivy-backed FTS index on text_content."""
    start = time.perf_counter()
    try:
        tbl.create_fts_index("text_content", replace=True)
    except TypeError:
        # Older LanceDB API without replace kwarg
        tbl.create_fts_index("text_content")
    return (time.perf_counter() - start) * 1000


def lance_create_vector_index(tbl: Any) -> float | None:
    """Create an IVF-PQ vector index on the embedding column."""
    n = tbl.count_rows()
    if n < 256:
        return None
    n_partitions = min(256, max(1, n // 40))
    start = time.perf_counter()
    try:
        tbl.create_index(
            vector_column_name="embedding",
            metric="cosine",
            num_partitions=n_partitions,
            replace=True,
        )
    except (TypeError, Exception):
        # Newer/Alternative LanceDB API: column name as first positional arg
        tbl.create_index("embedding", metric="cosine", replace=True)
    return (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# LanceDB queries
# ---------------------------------------------------------------------------

def _to_dicts(result: pa.Table) -> list[dict]:
    """Flatten a LanceDB search result to a list of dicts, truncating previews."""
    rows = result.to_pylist()
    for r in rows:
        text = r.pop("text_content", "") or ""
        r.pop("embedding", None)
        r["preview"] = text[:220].replace("\n", " ")
    return rows


def lance_fts_query(tbl: Any, query: str, limit: int) -> tuple[list[dict], float]:
    start = time.perf_counter()
    result = tbl.search(query, query_type="fts").limit(limit).to_arrow()
    return _to_dicts(result), (time.perf_counter() - start) * 1000


def lance_vector_query(
    tbl: Any, embedding: list[float], limit: int
) -> tuple[list[dict], float]:
    start = time.perf_counter()
    result = (
        tbl.search(embedding, vector_column_name="embedding")
        .limit(limit)
        .to_arrow()
    )
    return _to_dicts(result), (time.perf_counter() - start) * 1000


def lance_hybrid_rrf(
    tbl: Any,
    query: str,
    embedding: list[float],
    limit: int,
    rrf_k: int = 60,
) -> tuple[list[dict], float]:
    """
    Reciprocal Rank Fusion of FTS and vector results.
    Runs FTS and vector independently, then combines with RRF scoring.
    This is explicit rather than using LanceDB's built-in hybrid mode to avoid
    requiring a registered embedding function.
    """
    start = time.perf_counter()
    fts_rows, _ = lance_fts_query(tbl, query, limit * 2)
    vec_rows, _ = lance_vector_query(tbl, embedding, limit * 2)

    rrf_scores: dict[int, float] = {}
    for rank, r in enumerate(fts_rows, 1):
        cid = r["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    for rank, r in enumerate(vec_rows, 1):
        cid = r["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    # Deduplicate: prefer the dict from fts_rows (has FTS score field if any)
    by_cid: dict[int, dict] = {}
    for r in vec_rows + fts_rows:  # fts_rows overwrites, kept last
        by_cid[r["chunk_id"]] = r

    ranked = sorted(by_cid.values(), key=lambda r: -rrf_scores[r["chunk_id"]])[:limit]
    for i, r in enumerate(ranked, 1):
        r["rrf_score"] = round(rrf_scores[r["chunk_id"]], 6)
        r["rrf_rank"] = i

    return ranked, (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# Tokenization diagnostic
# ---------------------------------------------------------------------------

def lance_tokenization_diagnostic(db: lancedb.DBConnection) -> dict[str, Any]:
    """
    Infer Tantivy's tokenization behavior for alphanumeric identifiers by creating
    a temporary mini-table and observing which test strings match each query.

    This is the LanceDB side of the tokenization divergence matrix. Compare the
    results with pg_stemming_diagnostic to detect differences that would cause
    exact-identifier recall to diverge between PG17 and LanceDB.
    """
    diag_name = "_tokenization_diag"
    arrow = pa.table({
        "id": pa.array(range(len(_TOKENIZATION_TEST_STRINGS)), type=pa.int32()),
        "text": pa.array(_TOKENIZATION_TEST_STRINGS, type=pa.utf8()),
    })
    if diag_name in db.table_names():
        db.drop_table(diag_name)
    dt = db.create_table(diag_name, data=arrow)
    try:
        dt.create_fts_index("text", replace=True)
    except TypeError:
        dt.create_fts_index("text")

    results: dict[str, Any] = {
        "test_corpus": _TOKENIZATION_TEST_STRINGS,
        "queries": {},
    }
    for q in _TOKENIZATION_QUERIES:
        try:
            rows = (
                dt.search(q, query_type="fts")
                .limit(len(_TOKENIZATION_TEST_STRINGS))
                .to_arrow()
                .to_pylist()
            )
            results["queries"][q] = [{"id": r["id"], "text": r["text"]} for r in rows]
        except Exception as exc:
            results["queries"][q] = {"error": str(exc)}

    db.drop_table(diag_name)
    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _group_by_uri(rows: list[dict]) -> list[dict]:
    """Group flat chunk rows by source_uri for parent-level summary display."""
    by_uri: dict[str, dict] = {}
    ordered: list[dict] = []
    for r in rows:
        uri = r.get("source_uri", "")
        if uri not in by_uri:
            entry: dict[str, Any] = {"source_uri": uri, "chunks": []}
            by_uri[uri] = entry
            ordered.append(entry)
        by_uri[uri]["chunks"].append({k: v for k, v in r.items() if k != "source_uri"})
    return ordered


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_spike(args: argparse.Namespace) -> dict[str, Any]:
    queries = args.query or DEFAULT_QUERIES
    embedding_model = _load_embedding_model()
    embedding_source = "real" if embedding_model is not None else "zero_fallback"
    extension = f".{args.extension_filter.lstrip('.')}"

    rows: list[dict] = []
    extract_ms: float = 0.0
    pg_stemming: dict | None = None
    pg_baselines: dict[str, Any] = {}

    # --- PG17 phase ---
    needs_pg = not (args.skip_ingest and args.skip_pg_baseline and args.skip_stemming)
    if needs_pg:
        print(f"[PG17] Connecting to {args.host}:{args.port}/{args.database}...", file=sys.stderr)
        with pg_connect(args) as pg_conn:
            if not args.skip_ingest:
                print(f"[PG17] Extracting {extension} chunks...", file=sys.stderr)
                rows, extract_ms = pg_extract_chunks(pg_conn, extension, args.pg_limit)
                print(
                    f"[PG17] Extracted {len(rows):,} chunks in {extract_ms:.0f}ms",
                    file=sys.stderr,
                )

            if not args.skip_stemming:
                print("[PG17] Running stemming diagnostic...", file=sys.stderr)
                pg_stemming = pg_stemming_diagnostic(pg_conn, _TOKENIZATION_TEST_STRINGS[:4])

            if not args.skip_pg_baseline:
                print("[PG17] Running partitioned-semantic baseline...", file=sys.stderr)
                for q in queries:
                    emb = _encode(embedding_model, q)
                    baseline_rows, baseline_ms = pg_partitioned_semantic_baseline(
                        pg_conn,
                        document_table=args.document_table,
                        query=q,
                        query_embedding=emb,
                        extension_filter=extension,
                    )
                    pg_baselines[q] = {
                        "wall_ms": round(baseline_ms, 2),
                        "parents": _group_by_uri(baseline_rows),
                    }
                    print(
                        f"[PG17] '{q}': {len(baseline_rows)} child rows "
                        f"in {baseline_ms:.1f}ms",
                        file=sys.stderr,
                    )

    # --- LanceDB phase ---
    lance_path = Path(args.lance_path)
    print(f"[LanceDB] Connecting to {lance_path}...", file=sys.stderr)
    db = lancedb.connect(str(lance_path))

    ingest_ms: float = 0.0
    fts_idx_ms: float | None = None
    vec_idx_ms: float | None = None

    if args.skip_ingest and args.table_name in db.table_names():
        print(
            f"[LanceDB] Opening existing table '{args.table_name}'...",
            file=sys.stderr,
        )
        tbl = db.open_table(args.table_name)
    else:
        if not rows:
            sys.exit(
                "ERROR: No rows extracted from PG17. "
                "Cannot ingest into LanceDB. Remove --skip-ingest or check PG connection."
            )
        print(
            f"[LanceDB] Building PyArrow table from {len(rows):,} rows...",
            file=sys.stderr,
        )
        arrow_tbl = build_arrow_table(rows)

        print(f"[LanceDB] Ingesting into table '{args.table_name}'...", file=sys.stderr)
        tbl, ingest_ms = lance_ingest(db, args.table_name, arrow_tbl)
        print(f"[LanceDB] Ingested {len(rows):,} rows in {ingest_ms:.0f}ms", file=sys.stderr)

        print("[LanceDB] Creating FTS index...", file=sys.stderr)
        fts_idx_ms = lance_create_fts_index(tbl)
        print(f"[LanceDB] FTS index: {fts_idx_ms:.0f}ms", file=sys.stderr)

        if not args.skip_vector_index:
            print("[LanceDB] Creating vector index...", file=sys.stderr)
            vec_idx_ms = lance_create_vector_index(tbl)
            if vec_idx_ms is not None:
                print(f"[LanceDB] Vector index: {vec_idx_ms:.0f}ms", file=sys.stderr)
            else:
                print("[LanceDB] Skipped vector index (table too small).", file=sys.stderr)

    # --- Tokenization diagnostic ---
    lance_tokenization: dict | None = None
    if not args.skip_tokenization:
        print("[LanceDB] Running tokenization diagnostic...", file=sys.stderr)
        lance_tokenization = lance_tokenization_diagnostic(db)

    # --- Benchmark queries ---
    print("[LanceDB] Running benchmark queries...", file=sys.stderr)
    query_results = []
    for q in queries:
        emb = _encode(embedding_model, q)

        fts_rows, fts_ms = lance_fts_query(tbl, q, args.top_k)
        vec_rows, vec_ms = lance_vector_query(tbl, emb, args.top_k)
        hyb_rows, hyb_ms = lance_hybrid_rrf(tbl, q, emb, args.top_k)

        print(
            f"[LanceDB] '{q}': FTS {fts_ms:.1f}ms ({len(fts_rows)} results), "
            f"vector {vec_ms:.1f}ms, hybrid-RRF {hyb_ms:.1f}ms",
            file=sys.stderr,
        )

        query_results.append({
            "query": q,
            "embedding_source": embedding_source,
            "lance_fts": {
                "wall_ms": round(fts_ms, 2),
                "by_uri": _group_by_uri(fts_rows),
            },
            "lance_vector": {
                "wall_ms": round(vec_ms, 2),
                "by_uri": _group_by_uri(vec_rows),
            },
            "lance_hybrid_rrf": {
                "wall_ms": round(hyb_ms, 2),
                "by_uri": _group_by_uri(hyb_rows),
            },
            "pg17_partitioned_semantic": pg_baselines.get(q),
        })

    return {
        "lance_path": str(lance_path),
        "table_name": args.table_name,
        "extension_filter": args.extension_filter,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_source": embedding_source,
        "corpus": {
            "chunk_count": len(rows) or tbl.count_rows(),
            "extract_ms": round(extract_ms, 2) if extract_ms else None,
            "ingest_ms": round(ingest_ms, 2) if ingest_ms else None,
            "fts_index_ms": round(fts_idx_ms, 2) if fts_idx_ms is not None else None,
            "vector_index_ms": round(vec_idx_ms, 2) if vec_idx_ms is not None else None,
        },
        "tokenization_diagnostic": {
            "pg17_simple_and_english": pg_stemming,
            "lance_tantivy": lance_tokenization,
        },
        "queries": query_results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LanceDB embedded sidecar comparison script (Phase 2 RAG spike).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pg = p.add_argument_group("PG17 connection (spike DB)")
    pg.add_argument("--host", default=os.environ.get("PGTEXTSEARCH_HOST", "localhost"))
    pg.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PGTEXTSEARCH_PORT", "55432")),
    )
    pg.add_argument(
        "--database",
        default=os.environ.get("PGTEXTSEARCH_DATABASE", "rag_vector_restore_20260521"),
    )
    pg.add_argument("--user", default=os.environ.get("POSTGRES_USER", "rag_user"))
    pg.add_argument("--password", default=os.environ.get("POSTGRES_PASSWORD", "rag_password"))
    pg.add_argument("--document-table", default=DEFAULT_PG_DOCUMENT_TABLE)

    ld = p.add_argument_group("LanceDB config")
    ld.add_argument("--lance-path", default=DEFAULT_LANCE_PATH,
                    help="Directory path for the embedded LanceDB database")
    ld.add_argument("--table-name", default=DEFAULT_TABLE_NAME)

    q = p.add_argument_group("Query config")
    q.add_argument("--query", action="append",
                   help="Query to benchmark; may be repeated. Default: EV6 charging, EV6 battery")
    q.add_argument("--extension-filter", default=DEFAULT_EXTENSION_FILTER,
                   help="File extension to extract (default: txt)")
    q.add_argument("--top-k", type=int, default=10)
    q.add_argument("--pg-limit", type=int, default=None,
                   help="Cap rows extracted from PG17 (for rapid integration testing)")

    sk = p.add_argument_group("Skip flags (for incremental re-runs)")
    sk.add_argument("--skip-ingest", action="store_true",
                    help="Skip PG extraction + LanceDB ingestion; open existing table")
    sk.add_argument("--skip-vector-index", action="store_true",
                    help="Skip building the IVF-PQ vector index")
    sk.add_argument("--skip-tokenization", action="store_true",
                    help="Skip the Tantivy tokenization diagnostic mini-table")
    sk.add_argument("--skip-stemming", action="store_true",
                    help="Skip the PG17 to_tsvector stemming diagnostic")
    sk.add_argument("--skip-pg-baseline", action="store_true",
                    help="Skip running the PG17 partitioned-semantic baseline queries")

    p.add_argument("--output-json", type=Path,
                   help="Write JSON output to this file instead of stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_spike(args)
    except (psycopg2.Error, Exception) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

    rendered = json.dumps(result, indent=2, default=str)
    if args.output_json:
        args.output_json.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output_json}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
