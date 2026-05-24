#!/usr/bin/env python3
"""
Read-only-ish pg_textsearch comparison for the isolated PG17 spike database.

The script can optionally rebuild a document-level text table from
document_chunks. Query mode only reads from that table and reports raw BM25 plus
strict all-term document matches, and a parent-child fulfillment query.

Child-chunk selection modes (--child-selection-mode):
  reading-order        First N chunks per parent by chunk_index (no embedding needed)
  partitioned-semantic Top K chunks per parent ranked by vector distance
  composite-global     All children of top M parents, ranked by parent BM25 then vector distance
  pure-vector-global   All children of top M parents, ranked purely by vector distance

Semantic modes require sentence-transformers (soft dependency). If unavailable,
the script warns and falls back to zero-vectors; structural and latency results
remain valid but quality rankings are meaningless.
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
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

DEFAULT_QUERIES = ["EV6", "EV6 charging", "EV6 battery"]
DEFAULT_DOCUMENT_TABLE = "search_spike_document_text"
DEFAULT_INDEX_NAME = "search_spike_document_text_content_bm25"
DEFAULT_PARENT_LIMIT = 5
DEFAULT_CHILD_LIMIT_PER_PARENT = 5
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
CHILD_SELECTION_MODES = (
    "reading-order",
    "partitioned-semantic",
    "composite-global",
    "pure-vector-global",
)


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
            "semantic child-selection modes will use zero-vector fallback. "
            "Structural and latency results remain valid; quality rankings are not.",
            file=sys.stderr,
        )
        return None


def _encode_query(model, query: str) -> list[float]:
    """Encode query string to float list, or return a zero vector if model is None."""
    if model is None:
        return [0.0] * EMBEDDING_DIM
    embedding = model.encode(query)
    return embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)


def _embedding_to_pg_literal(embedding: list[float]) -> str:
    """Format a float list as a PostgreSQL vector literal compatible with %s::vector."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def normalize_extension(extension: str) -> str:
    return extension if extension.startswith(".") else f".{extension}"


def connect(args: argparse.Namespace):
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.database,
        user=args.user,
        password=args.password,
    )


def rebuild_document_table(conn, table_name: str) -> None:
    table_ident = sql.Identifier(table_name)
    index_ident = sql.Identifier(DEFAULT_INDEX_NAME)
    with conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table_ident))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {} AS
                SELECT
                    source_uri,
                    LOWER(REGEXP_REPLACE(
                        source_uri,
                        '^.*(\\.[^.\\\\/]+)$',
                        '\\1'
                    )) AS extension,
                    STRING_AGG(text_content, E'\n\n' ORDER BY chunk_index) AS content,
                    COUNT(*) AS chunk_count
                FROM document_chunks
                GROUP BY source_uri
                """
            ).format(table_ident)
        )
        cursor.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(index_ident))
        cursor.execute(
            sql.SQL(
                """
                CREATE INDEX {} ON {}
                USING bm25(content)
                WITH (text_config='english')
                """
            ).format(index_ident, table_ident)
        )
    conn.commit()


def document_table_stats(conn, table_name: str) -> dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*)::int AS documents,
                    COALESCE(SUM(chunk_count), 0)::int AS chunks
                FROM {}
                """
            ).format(sql.Identifier(table_name))
        )
        return dict(cursor.fetchone() or {})


def extension_where(extensions: list[str]) -> tuple[str, list[Any]]:
    if not extensions:
        return "", []
    clauses = []
    params: list[Any] = []
    for extension in extensions:
        clauses.append("source_uri ILIKE %s")
        params.append(f"%{normalize_extension(extension)}")
    return f"WHERE ({' OR '.join(clauses)})", params


# ---------------------------------------------------------------------------
# BM25 document-level query
# ---------------------------------------------------------------------------

def run_query(
    conn,
    *,
    table_name: str,
    query: str,
    top_k: int,
    extensions: list[str],
    strict_all_terms: bool,
) -> tuple[list[dict[str, Any]], float]:
    base_where, params = extension_where(extensions)
    where_parts = [base_where.removeprefix("WHERE ").strip()] if base_where else []
    if strict_all_terms:
        where_parts.append("to_tsvector('english', content) @@ plainto_tsquery('english', %s)")
        params.append(query)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    query_sql = sql.SQL(
        f"""
        SELECT
            source_uri,
            chunk_count,
            content <@> %s AS bm25_score,
            LEFT(REPLACE(content, E'\n', ' '), 220) AS preview
        FROM {{}}
        {where_sql}
        ORDER BY content <@> %s
        LIMIT %s
        """
    ).format(sql.Identifier(table_name))
    start = time.perf_counter()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query_sql, [query, *params, query, top_k])
        rows = [dict(row) for row in cursor.fetchall()]
    wall_ms = (time.perf_counter() - start) * 1000
    return rows, wall_ms


# ---------------------------------------------------------------------------
# Parent-child fulfillment query
# ---------------------------------------------------------------------------

def _build_child_cte_and_tail(
    child_selection_mode: str,
    embedding_literal: str | None,
    child_limit: int,
) -> tuple[str, str, list[Any]]:
    """
    Return (child_cte_sql, tail_sql, extra_params) for the given selection mode.

    All CTEs emit vector_distance and child_rank (NULL where unused) so that
    group_parent_child_rows always has the same result structure.
    """
    common_cols = (
        "p.parent_rank, p.source_uri, p.chunk_count AS parent_chunk_count, "
        "p.parent_bm25_score, c.chunk_id, c.chunk_index, c.text_content"
    )

    if child_selection_mode == "reading-order":
        cte = f"""child_chunks AS (
            SELECT
                {common_cols},
                NULL::float AS vector_distance,
                ROW_NUMBER() OVER (
                    PARTITION BY c.source_uri
                    ORDER BY c.chunk_index
                ) AS child_rank
            FROM ranked_parent_docs p
            JOIN document_chunks c ON c.source_uri = p.source_uri
        )"""
        tail = "WHERE child_rank <= %s ORDER BY parent_rank, chunk_index"
        extra: list[Any] = [child_limit]

    elif child_selection_mode == "partitioned-semantic":
        cte = f"""child_chunks AS (
            SELECT
                {common_cols},
                (c.embedding <=> %s::vector) AS vector_distance,
                ROW_NUMBER() OVER (
                    PARTITION BY c.source_uri
                    ORDER BY (c.embedding <=> %s::vector) ASC
                ) AS child_rank
            FROM ranked_parent_docs p
            JOIN document_chunks c ON c.source_uri = p.source_uri
        )"""
        tail = "WHERE child_rank <= %s ORDER BY parent_rank, child_rank"
        extra = [embedding_literal, embedding_literal, child_limit]

    elif child_selection_mode == "composite-global":
        cte = f"""child_chunks AS (
            SELECT
                {common_cols},
                (c.embedding <=> %s::vector) AS vector_distance,
                NULL::int AS child_rank
            FROM ranked_parent_docs p
            JOIN document_chunks c ON c.source_uri = p.source_uri
        )"""
        tail = "ORDER BY parent_bm25_score ASC, vector_distance ASC LIMIT %s"
        extra = [embedding_literal, child_limit]

    elif child_selection_mode == "pure-vector-global":
        cte = f"""child_chunks AS (
            SELECT
                {common_cols},
                (c.embedding <=> %s::vector) AS vector_distance,
                NULL::int AS child_rank
            FROM ranked_parent_docs p
            JOIN document_chunks c ON c.source_uri = p.source_uri
        )"""
        tail = "ORDER BY vector_distance ASC LIMIT %s"
        extra = [embedding_literal, child_limit]

    else:
        raise ValueError(f"Unknown child_selection_mode: {child_selection_mode!r}")

    return cte, tail, extra


def run_parent_child_query(
    conn,
    *,
    table_name: str,
    query: str,
    query_embedding: list[float] | None,
    parent_limit: int,
    child_limit: int,
    extensions: list[str],
    child_selection_mode: str = "reading-order",
    explain_analyze: bool = False,
) -> tuple[list[dict[str, Any]], float, dict[str, str] | None]:
    base_where, ext_params = extension_where(extensions)
    where_sql = base_where
    embedding_literal = (
        _embedding_to_pg_literal(query_embedding) if query_embedding is not None else None
    )
    child_cte, tail_sql, child_extra = _build_child_cte_and_tail(
        child_selection_mode, embedding_literal, child_limit
    )
    query_sql = sql.SQL(
        f"""
        WITH top_parent_docs AS (
            SELECT
                source_uri,
                chunk_count,
                content <@> %s AS parent_bm25_score
            FROM {{}}
            {where_sql}
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
        {child_cte}
        SELECT
            parent_rank,
            source_uri,
            parent_chunk_count,
            parent_bm25_score,
            chunk_id,
            chunk_index,
            vector_distance,
            child_rank,
            LEFT(REPLACE(text_content, E'\n', ' '), 220) AS preview
        FROM child_chunks
        {tail_sql}
        """
    ).format(sql.Identifier(table_name))

    all_params = [query, *ext_params, query, parent_limit, *child_extra]

    explain_output: dict[str, str] | None = None
    if explain_analyze:
        explain_sql = sql.SQL("EXPLAIN (ANALYZE, FORMAT TEXT) ") + query_sql
        explain_output = {}
        with conn.cursor() as cursor:
            cursor.execute(explain_sql, all_params)
            explain_output["default_plan"] = "\n".join(
                row[0] for row in cursor.fetchall()
            )
        with conn.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off")
            cursor.execute(explain_sql, all_params)
            explain_output["forced_index_plan"] = "\n".join(
                row[0] for row in cursor.fetchall()
            )
            cursor.execute("RESET enable_seqscan")

    start = time.perf_counter()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query_sql, all_params)
        rows = [dict(row) for row in cursor.fetchall()]
    wall_ms = (time.perf_counter() - start) * 1000
    return rows, wall_ms, explain_output


def group_parent_child_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents: list[dict[str, Any]] = []
    by_source_uri: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_uri = row["source_uri"]
        parent = by_source_uri.get(source_uri)
        if parent is None:
            parent = {
                "parent_rank": row["parent_rank"],
                "source_uri": source_uri,
                "parent_chunk_count": row["parent_chunk_count"],
                "parent_bm25_score": row["parent_bm25_score"],
                "fulfilled_chunks": [],
            }
            by_source_uri[source_uri] = parent
            parents.append(parent)
        parent["fulfilled_chunks"].append({
            "chunk_id": row["chunk_id"],
            "chunk_index": row["chunk_index"],
            "child_rank": row["child_rank"],
            "vector_distance": row.get("vector_distance"),
            "preview": row["preview"],
        })
    return parents


# ---------------------------------------------------------------------------
# Lexical stemming diagnostic
# ---------------------------------------------------------------------------

def run_stemming_diagnostic(conn) -> dict[str, Any]:
    """Return how the english and simple dictionaries normalize EV6 and charging."""
    results = {}
    with conn.cursor() as cursor:
        for config in ("english", "simple"):
            cursor.execute(
                "SELECT to_tsvector(%s, %s)::text",
                (config, "EV6 charging"),
            )
            row = cursor.fetchone()
            results[config] = row[0] if row else ""
    return results


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def compare_queries(args: argparse.Namespace) -> dict[str, Any]:
    queries = args.query or DEFAULT_QUERIES
    extensions = args.extension or []

    embedding_model = None
    embedding_warning: str | None = None
    if args.child_selection_mode != "reading-order":
        embedding_model = _load_embedding_model()
        if embedding_model is None:
            embedding_warning = (
                "sentence_transformers unavailable; zero-vector fallback active. "
                "Structural and latency results are valid. Quality rankings are not."
            )

    with connect(args) as conn:
        if args.rebuild_document_table:
            rebuild_document_table(conn, args.document_table)
        stats = document_table_stats(conn, args.document_table)

        stemming_diagnostic: dict[str, Any] | None = None
        if args.stemming_diagnostic:
            stemming_diagnostic = run_stemming_diagnostic(conn)

        results = []
        for query in queries:
            raw_rows, raw_ms = run_query(
                conn,
                table_name=args.document_table,
                query=query,
                top_k=args.top_k,
                extensions=extensions,
                strict_all_terms=False,
            )
            strict_rows, strict_ms = run_query(
                conn,
                table_name=args.document_table,
                query=query,
                top_k=args.top_k,
                extensions=extensions,
                strict_all_terms=True,
            )

            query_embedding: list[float] | None = None
            if args.child_selection_mode != "reading-order":
                query_embedding = _encode_query(embedding_model, query)

            pc_rows, pc_ms, explain_out = run_parent_child_query(
                conn,
                table_name=args.document_table,
                query=query,
                query_embedding=query_embedding,
                parent_limit=args.parent_limit,
                child_limit=args.child_limit_per_parent,
                extensions=extensions,
                child_selection_mode=args.child_selection_mode,
                explain_analyze=args.explain_analyze,
            )

            pc_result: dict[str, Any] = {
                "wall_time_ms": round(pc_ms, 2),
                "child_selection_mode": args.child_selection_mode,
                "parent_limit": args.parent_limit,
                "child_limit": args.child_limit_per_parent,
                "embedding_source": (
                    "real" if embedding_model is not None
                    else "zero_fallback" if query_embedding is not None
                    else "none"
                ),
                "parents": group_parent_child_rows(pc_rows),
            }
            if explain_out:
                pc_result["explain_analyze"] = explain_out

            results.append({
                "query": query,
                "raw_bm25": {"wall_time_ms": round(raw_ms, 2), "results": raw_rows},
                "strict_all_terms": {"wall_time_ms": round(strict_ms, 2), "results": strict_rows},
                "parent_child": pc_result,
            })

    output: dict[str, Any] = {
        "database": {
            "host": args.host,
            "port": args.port,
            "name": args.database,
            "document_table": args.document_table,
            "document_table_stats": stats,
        },
        "top_k": args.top_k,
        "extensions": extensions,
        "child_selection_mode": args.child_selection_mode,
        "embedding_model": EMBEDDING_MODEL if args.child_selection_mode != "reading-order" else None,
        "queries": results,
    }
    if embedding_warning:
        output["embedding_warning"] = embedding_warning
    if stemming_diagnostic is not None:
        output["stemming_diagnostic"] = stemming_diagnostic
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare document-level BM25 behavior in the pg_textsearch spike DB."
    )
    parser.add_argument("--host", default=os.environ.get("PGTEXTSEARCH_HOST", "localhost"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PGTEXTSEARCH_PORT", "55432")),
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("PGTEXTSEARCH_DATABASE", "rag_vector_restore_20260521"),
    )
    parser.add_argument("--user", default=os.environ.get("POSTGRES_USER", "rag_user"))
    parser.add_argument("--password", default=os.environ.get("POSTGRES_PASSWORD", "rag_password"))
    parser.add_argument("--document-table", default=DEFAULT_DOCUMENT_TABLE)
    parser.add_argument("--rebuild-document-table", action="store_true")
    parser.add_argument("--query", action="append", help="Query to compare; may be repeated")
    parser.add_argument("--extension", action="append", help="Extension filter; may be repeated")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--parent-limit", type=int, default=DEFAULT_PARENT_LIMIT)
    parser.add_argument(
        "--child-limit-per-parent",
        type=int,
        default=DEFAULT_CHILD_LIMIT_PER_PARENT,
        help=(
            "Child chunks per parent for partitioned-semantic mode; "
            "total child result limit for composite-global and pure-vector-global."
        ),
    )
    parser.add_argument(
        "--child-selection-mode",
        choices=CHILD_SELECTION_MODES,
        default="reading-order",
        help="Child chunk selection strategy within BM25-selected parent documents.",
    )
    parser.add_argument(
        "--explain-analyze",
        action="store_true",
        help=(
            "Run EXPLAIN (ANALYZE, FORMAT TEXT) on the parent-child query "
            "under default and forced-index (SET enable_seqscan = off) plans."
        ),
    )
    parser.add_argument(
        "--stemming-diagnostic",
        action="store_true",
        help="Log how english and simple dictionaries normalize the query terms.",
    )
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = compare_queries(args)
    except psycopg2.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(output, indent=2, default=str)
    if args.output_json:
        args.output_json.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output_json}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
