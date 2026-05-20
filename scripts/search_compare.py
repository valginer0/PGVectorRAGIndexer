#!/usr/bin/env python3
"""
Read-only search comparison for real corpora.

Runs each query twice against an existing PGVectorRAGIndexer API:

- baseline: current desktop-style chunk over-fetch plus source_uri de-duplication
- document_level: opt-in API grouping with identifier-token tail suppression

The script does not upload, delete, or mutate indexed documents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop_app.utils.search_limits import candidate_limit_for_unique_files


class SearchCompareHTTPError(RuntimeError):
    pass


class SearchCompareHTTPClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def health(self) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
        if response.status_code >= 400:
            raise SearchCompareHTTPError(
                f"GET {self.base_url}/health failed ({response.status_code}): {response.text[:500]}"
            )
        return response.json()

    def search(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        start = time.perf_counter()
        response = self.session.post(f"{self.api_base}/search", json=payload, timeout=self.timeout)
        wall_ms = (time.perf_counter() - start) * 1000
        if response.status_code >= 400:
            raise SearchCompareHTTPError(
                f"POST {self.api_base}/search failed ({response.status_code}): {response.text[:500]}"
            )
        return response.json(), wall_ms


def result_score(result: dict[str, Any]) -> float:
    for key in ("rank_score", "combined_score", "relevance_score", "score"):
        value = result.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def dedupe_first_by_source_uri(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for result in results:
        source_uri = str(result.get("source_uri") or result.get("document_id") or "")
        if not source_uri or source_uri in seen:
            continue
        seen.add(source_uri)
        deduped.append(result)
    return deduped


def top_file_details(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    details = []
    for rank, result in enumerate(results[:limit], start=1):
        details.append({
            "rank": rank,
            "source_uri": result.get("source_uri"),
            "document_type": result.get("document_type") or (result.get("metadata") or {}).get("type"),
            "chunk_index": result.get("chunk_index"),
            "score": result_score(result),
            "rank_score": result.get("rank_score"),
            "relevance_score": result.get("relevance_score"),
        })
    return details


def group_by_document_confirmed(response: dict[str, Any]) -> bool:
    diagnostics = response.get("diagnostics") or {}
    grouping = diagnostics.get("group_by_document") or {}
    return bool(grouping.get("active"))


def compare_top_files(baseline_files: list[str], document_level_files: list[str]) -> dict[str, Any]:
    baseline_ranks = {source_uri: index for index, source_uri in enumerate(baseline_files, start=1)}
    document_level_ranks = {
        source_uri: index for index, source_uri in enumerate(document_level_files, start=1)
    }
    common = sorted(set(baseline_ranks) & set(document_level_ranks))
    return {
        "same_order": baseline_files == document_level_files,
        "added_by_document_level": [
            source_uri for source_uri in document_level_files if source_uri not in baseline_ranks
        ],
        "removed_by_document_level": [
            source_uri for source_uri in baseline_files if source_uri not in document_level_ranks
        ],
        "rank_changes": [
            {
                "source_uri": source_uri,
                "baseline_rank": baseline_ranks[source_uri],
                "document_level_rank": document_level_ranks[source_uri],
            }
            for source_uri in common
            if baseline_ranks[source_uri] != document_level_ranks[source_uri]
        ],
    }


def build_filters(args: argparse.Namespace) -> dict[str, Any] | None:
    filters: dict[str, Any] = {}
    if args.filters_json:
        loaded = json.loads(args.filters_json)
        if not isinstance(loaded, dict):
            raise ValueError("--filters-json must decode to an object")
        filters.update(loaded)
    if args.document_type and args.document_type != "*":
        filters["type"] = args.document_type
    extensions = [ext for ext in (args.extension or []) if ext and ext != "*"]
    if extensions:
        filters["extensions"] = extensions
    return filters or None


def load_queries(args: argparse.Namespace) -> list[dict[str, str]]:
    queries: list[str] = list(args.query or [])
    if args.queries_file:
        for line in args.queries_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                queries.append(stripped)
    if not queries:
        raise ValueError("provide at least one --query or --queries-file entry")
    return [{"id": f"q{index:03d}", "query": query} for index, query in enumerate(queries, start=1)]


def build_search_payload(
    *,
    query: str,
    top_k: int | None,
    min_score: float,
    filters: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "top_k": top_k,
        "min_score": min_score,
        "use_hybrid": True,
    }
    if filters:
        payload["filters"] = filters
    return payload


def execute_query_pair(
    client: SearchCompareHTTPClient,
    query_item: dict[str, str],
    *,
    top_k: int,
    min_score: float,
    filters: dict[str, Any] | None,
    literal_anchor_threshold: float,
    literal_tail_threshold: float,
) -> dict[str, Any]:
    baseline_payload = build_search_payload(
        query=query_item["query"],
        top_k=candidate_limit_for_unique_files(top_k),
        min_score=min_score,
        filters=filters,
    )
    baseline_response, baseline_wall_ms = client.search(baseline_payload)
    baseline_chunks = list(baseline_response.get("results") or [])
    baseline_files = dedupe_first_by_source_uri(baseline_chunks)[:top_k]

    document_payload = build_search_payload(
        query=query_item["query"],
        top_k=top_k,
        min_score=min_score,
        filters=filters,
    )
    document_payload.update({
        "group_by_document": True,
        "literal_tail_suppression": "identifier-token",
        "literal_anchor_threshold": literal_anchor_threshold,
        "literal_tail_threshold": literal_tail_threshold,
    })
    document_response, document_wall_ms = client.search(document_payload)
    document_results = list(document_response.get("results") or [])[:top_k]

    baseline_top_files = [str(result.get("source_uri", "")) for result in baseline_files]
    document_top_files = [str(result.get("source_uri", "")) for result in document_results]

    return {
        "id": query_item["id"],
        "query": query_item["query"],
        "baseline": {
            "payload_top_k": baseline_payload["top_k"],
            "api_search_time_ms": baseline_response.get("search_time_ms"),
            "wall_time_ms": round(baseline_wall_ms, 2),
            "raw_result_count": len(baseline_chunks),
            "displayed_file_count": len(baseline_files),
            "top_files": baseline_top_files,
            "top_file_details": top_file_details(baseline_files, top_k),
        },
        "document_level": {
            "confirmed": group_by_document_confirmed(document_response),
            "api_search_time_ms": document_response.get("search_time_ms"),
            "wall_time_ms": round(document_wall_ms, 2),
            "raw_result_count": len(document_response.get("results") or []),
            "displayed_file_count": len(document_results),
            "api_diagnostics": document_response.get("diagnostics"),
            "top_files": document_top_files,
            "top_file_details": top_file_details(document_results, top_k),
        },
        "comparison": compare_top_files(baseline_top_files, document_top_files),
    }


def run(args: argparse.Namespace) -> int:
    try:
        queries = load_queries(args)
        filters = build_filters(args)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    client = SearchCompareHTTPClient(
        base_url=args.api_base,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    output: dict[str, Any] = {
        "api_base": args.api_base,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "filters": filters,
        "query_count": len(queries),
        "document_level_options": {
            "group_by_document": True,
            "literal_tail_suppression": "identifier-token",
            "literal_anchor_threshold": args.literal_anchor_threshold,
            "literal_tail_threshold": args.literal_tail_threshold,
        },
    }
    try:
        output["health"] = client.health()
        output["results"] = [
            execute_query_pair(
                client,
                query,
                top_k=args.top_k,
                min_score=args.min_score,
                filters=filters,
                literal_anchor_threshold=args.literal_anchor_threshold,
                literal_tail_threshold=args.literal_tail_threshold,
            )
            for query in queries
        ]
    except (requests.RequestException, SearchCompareHTTPError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    rendered = json.dumps(output, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output_json}")
    else:
        print(rendered)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only comparison of default and document-level search modes."
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("SEARCH_EVAL_API_BASE", "http://localhost:8000"),
        help="Base API URL before /api/v1 (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PGVECTOR_API_KEY") or os.environ.get("API_KEY"),
        help="API key for authenticated servers; defaults to PGVECTOR_API_KEY or API_KEY",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds")
    parser.add_argument("--query", action="append", help="Query to compare; may be repeated")
    parser.add_argument("--queries-file", type=Path, help="Plain-text query file, one query per line")
    parser.add_argument("--top-k", type=int, default=10, help="Displayed file count to compare")
    parser.add_argument("--min-score", type=float, default=0.3, help="Search min_score")
    parser.add_argument("--document-type", help="Optional document type filter; use * for all")
    parser.add_argument("--extension", action="append", help="Optional extension filter; may be repeated")
    parser.add_argument("--filters-json", help="Additional raw search filters as a JSON object")
    parser.add_argument(
        "--literal-anchor-threshold",
        type=float,
        default=10.0,
        help="API literal-tail anchor threshold (default: 10.0)",
    )
    parser.add_argument(
        "--literal-tail-threshold",
        type=float,
        default=0.1,
        help="API literal-tail tail threshold (default: 0.1)",
    )
    parser.add_argument("--output-json", type=Path, help="Write comparison JSON to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
