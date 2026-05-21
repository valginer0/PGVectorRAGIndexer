#!/usr/bin/env python3
"""
Read-only-ish pg_textsearch comparison for the isolated PG17 spike database.

The script can optionally rebuild a document-level text table from
document_chunks. Query mode only reads from that table and reports raw BM25 plus
strict all-term document matches.
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


def compare_queries(args: argparse.Namespace) -> dict[str, Any]:
    queries = args.query or DEFAULT_QUERIES
    extensions = args.extension or []
    with connect(args) as conn:
        if args.rebuild_document_table:
            rebuild_document_table(conn, args.document_table)
        stats = document_table_stats(conn, args.document_table)
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
            results.append({
                "query": query,
                "raw_bm25": {
                    "wall_time_ms": round(raw_ms, 2),
                    "results": raw_rows,
                },
                "strict_all_terms": {
                    "wall_time_ms": round(strict_ms, 2),
                    "results": strict_rows,
                },
            })
    return {
        "database": {
            "host": args.host,
            "port": args.port,
            "name": args.database,
            "document_table": args.document_table,
            "document_table_stats": stats,
        },
        "top_k": args.top_k,
        "extensions": extensions,
        "queries": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare document-level BM25 behavior in the pg_textsearch spike DB."
    )
    parser.add_argument("--host", default=os.environ.get("PGTEXTSEARCH_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PGTEXTSEARCH_PORT", "55432")))
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
