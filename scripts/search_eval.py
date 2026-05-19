#!/usr/bin/env python3
"""
Search evaluation fixture loader and CLI skeleton.

This first pass is intentionally offline: it validates the fixture corpus and
builds the query execution plan. Live indexing/search execution can be layered
on top of these helpers in the next step.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "search_eval"
VALID_QUERY_CLASSES = {
    "literal",
    "contextual",
    "hybrid",
    "filtered",
    "chunk_crowding",
    "negative",
}
QUERY_FILE_FIELDS = ("expected_files", "relevant_files", "forbidden_files")


@dataclass(frozen=True)
class FixtureSet:
    root: Path
    manifest: dict[str, Any]
    queries: dict[str, Any]

    @property
    def manifest_paths(self) -> set[str]:
        return {doc["path"] for doc in self.manifest.get("documents", [])}

    @property
    def query_items(self) -> list[dict[str, Any]]:
        return list(self.queries.get("queries", []))


@dataclass(frozen=True)
class QueryPlan:
    id: str
    query_class: str
    query: str
    filters: dict[str, Any]
    expected_files: list[str]
    relevant_files: list[str]
    forbidden_files: list[str]
    assertions: dict[str, Any]
    top_k_files: int
    backend_top_k: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class": self.query_class,
            "query": self.query,
            "filters": self.filters,
            "expected_files": self.expected_files,
            "relevant_files": self.relevant_files,
            "forbidden_files": self.forbidden_files,
            "assertions": self.assertions,
            "top_k_files": self.top_k_files,
            "backend_top_k": self.backend_top_k,
        }


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return loaded or {}


def load_fixture_set(root: Path = DEFAULT_FIXTURE_ROOT) -> FixtureSet:
    root = root.resolve()
    return FixtureSet(
        root=root,
        manifest=load_yaml(root / "manifest.yaml"),
        queries=load_yaml(root / "queries.yaml"),
    )


def validate_fixture_set(fixture_set: FixtureSet) -> list[str]:
    errors: list[str] = []
    manifest = fixture_set.manifest
    queries = fixture_set.queries

    namespace = manifest.get("namespace")
    default_metadata = manifest.get("default_metadata") or {}
    if namespace != "search_eval_v0":
        errors.append("manifest namespace must be search_eval_v0")
    if default_metadata.get("namespace") != namespace:
        errors.append("default_metadata.namespace must match manifest namespace")
    if default_metadata.get("category") != "search_eval":
        errors.append("default_metadata.category must be search_eval")

    document_paths = [doc.get("path") for doc in manifest.get("documents", [])]
    if len(document_paths) != len(set(document_paths)):
        errors.append("manifest contains duplicate document paths")

    for path in document_paths:
        if not path:
            errors.append("manifest contains a document without a path")
            continue
        document_path = fixture_set.root / path
        if not document_path.exists():
            errors.append(f"manifest references missing file: {path}")
        elif not document_path.is_file():
            errors.append(f"manifest path is not a file: {path}")
        elif not document_path.read_text(encoding="utf-8").strip():
            errors.append(f"fixture file is empty: {path}")

    if queries.get("default_filters") != {"namespace": namespace}:
        errors.append("queries.default_filters must match the manifest namespace")
    if queries.get("default_backend_top_k", 0) < queries.get("default_top_k_files", 0):
        errors.append("default_backend_top_k must be greater than or equal to default_top_k_files")

    query_items = queries.get("queries", [])
    query_ids = [item.get("id") for item in query_items]
    if len(query_ids) != len(set(query_ids)):
        errors.append("queries contain duplicate ids")

    manifest_paths = set(path for path in document_paths if path)
    for item in query_items:
        query_id = item.get("id", "<missing id>")
        if item.get("class") not in VALID_QUERY_CLASSES:
            errors.append(f"{query_id} has unknown class: {item.get('class')}")
        if not str(item.get("query", "")).strip():
            errors.append(f"{query_id} has an empty query")
        if not item.get("assertions"):
            errors.append(f"{query_id} has no assertions")

        assertions = item.get("assertions") or {}
        expected_files = item.get("expected_files") or []
        forbidden_files = item.get("forbidden_files") or []
        filters = item.get("filters") or {}

        if assertions.get("recall_at_5") is True and not expected_files:
            errors.append(f"{query_id} assertion recall_at_5 requires expected_files")
        if "first_expected_rank_lte" in assertions and not expected_files:
            errors.append(f"{query_id} assertion first_expected_rank_lte requires expected_files")
        if "literal_match_rank_lte" in assertions and not expected_files:
            errors.append(f"{query_id} assertion literal_match_rank_lte requires expected_files")
        if assertions.get("filters_respected") is True and not filters:
            errors.append(f"{query_id} assertion filters_respected requires filters")
        if "forbidden_at_5_eq" in assertions and not forbidden_files:
            errors.append(f"{query_id} assertion forbidden_at_5_eq requires forbidden_files")
        if "min_unique_files_at_5" in assertions:
            try:
                min_unique = int(assertions["min_unique_files_at_5"])
            except (TypeError, ValueError):
                errors.append(f"{query_id} assertion min_unique_files_at_5 must be an integer")
                min_unique = 0
            if min_unique < 1:
                errors.append(f"{query_id} assertion min_unique_files_at_5 must be positive")
            elif min_unique > len(manifest_paths):
                errors.append(
                    f"{query_id} assertion min_unique_files_at_5 exceeds manifest size"
                )

        for field in QUERY_FILE_FIELDS:
            for path in item.get(field, []) or []:
                if path not in manifest_paths:
                    errors.append(f"{query_id} {field} references file not in manifest: {path}")

        extensions = (item.get("filters") or {}).get("extensions")
        if extensions:
            for ext in extensions:
                if not str(ext).startswith("."):
                    errors.append(f"{query_id} extension filter must start with a dot: {ext}")
            for path in item.get("expected_files", []) or []:
                if Path(path).suffix not in extensions:
                    errors.append(
                        f"{query_id} expects {path}, but filter only allows {extensions}"
                    )

    return errors


def merge_filters(default_filters: dict[str, Any], query_filters: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(default_filters)
    if query_filters:
        merged.update(query_filters)
    return merged


def build_query_plans(fixture_set: FixtureSet) -> list[QueryPlan]:
    queries = fixture_set.queries
    default_filters = queries.get("default_filters") or {}
    default_top_k_files = int(queries.get("default_top_k_files", 5))
    default_backend_top_k = int(queries.get("default_backend_top_k", 100))
    plans: list[QueryPlan] = []

    for item in fixture_set.query_items:
        expected_files = list(item.get("expected_files") or [])
        relevant_files = list(item.get("relevant_files") or expected_files)
        plans.append(
            QueryPlan(
                id=item["id"],
                query_class=item["class"],
                query=item["query"],
                filters=merge_filters(default_filters, item.get("filters")),
                expected_files=expected_files,
                relevant_files=relevant_files,
                forbidden_files=list(item.get("forbidden_files") or []),
                assertions=dict(item.get("assertions") or {}),
                top_k_files=int(item.get("top_k_files", default_top_k_files)),
                backend_top_k=int(item.get("backend_top_k", default_backend_top_k)),
            )
        )

    return plans


def _result_score(result: dict[str, Any]) -> float:
    for key in ("relevance_score", "score", "combined_score"):
        if result.get(key) is not None:
            return float(result[key])
    return 0.0


def dedupe_chunks_by_source_uri(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_source: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, result in enumerate(results):
        source_uri = result.get("source_uri") or result.get("document_id")
        if not source_uri:
            continue
        current = best_by_source.get(source_uri)
        if current is None or _result_score(result) > _result_score(current[1]):
            best_by_source[source_uri] = (index, result)

    return [
        result
        for _, result in sorted(
            best_by_source.values(),
            key=lambda pair: (-_result_score(pair[1]), pair[0]),
        )
    ]


def normalize_result_path(source_uri: str, fixture_root: Path | None = None) -> str:
    path = Path(source_uri)
    if fixture_root and path.is_absolute():
        try:
            return path.relative_to(fixture_root).as_posix()
        except ValueError:
            pass

    marker = "/corpus/"
    normalized = source_uri.replace("\\", "/")
    # Fallback for API source URIs that point into this fixture corpus but are
    # not under the local fixture root, such as mapped container paths.
    if marker in normalized:
        return "corpus/" + normalized.split(marker, 1)[1]
    return normalized


def calculate_file_metrics(
    file_results: list[dict[str, Any]],
    query_plan: QueryPlan,
    fixture_root: Path | None = None,
) -> dict[str, Any]:
    top_k = query_plan.top_k_files
    result_files = [
        normalize_result_path(str(result.get("source_uri", "")), fixture_root)
        for result in file_results[:top_k]
    ]
    expected = set(query_plan.expected_files)
    relevant = set(query_plan.relevant_files or query_plan.expected_files)
    forbidden = set(query_plan.forbidden_files)

    first_expected_rank = None
    for index, result_file in enumerate(result_files, start=1):
        if result_file in expected:
            first_expected_rank = index
            break

    extensions = (query_plan.filters or {}).get("extensions") or []
    filter_violations = 0
    if extensions:
        filter_violations = sum(
            1 for result_file in result_files if Path(result_file).suffix not in extensions
        )

    precision_denominator = len(result_files) or 1
    return {
        "Recall@K": bool(expected and expected.intersection(result_files)),
        "MRR": 1.0 / first_expected_rank if first_expected_rank else 0.0,
        "Precision@K": sum(1 for path in result_files if path in relevant) / precision_denominator,
        "Forbidden@K": sum(1 for path in result_files if path in forbidden),
        "FirstExpectedRank": first_expected_rank,
        "UniqueFiles@K": len(set(result_files)),
        "FilterViolations": filter_violations,
    }


def run_validate(args: argparse.Namespace) -> int:
    fixture_set = load_fixture_set(args.fixture_root)
    errors = validate_fixture_set(fixture_set)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    plans = build_query_plans(fixture_set)
    print(
        f"Fixture set valid: {len(fixture_set.manifest_paths)} documents, "
        f"{len(plans)} queries"
    )
    return 0


def run_plan(args: argparse.Namespace) -> int:
    fixture_set = load_fixture_set(args.fixture_root)
    errors = validate_fixture_set(fixture_set)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    plans = build_query_plans(fixture_set)
    if args.json:
        print(json.dumps([plan.to_dict() for plan in plans], indent=2, sort_keys=True))
        return 0

    print(f"Query plan: {len(plans)} queries")
    for plan in plans:
        filters = json.dumps(plan.filters, sort_keys=True)
        print(
            f"- {plan.id} [{plan.query_class}] "
            f"top_files={plan.top_k_files} backend_top_k={plan.backend_top_k} "
            f"filters={filters}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and plan PGVectorRAGIndexer search evaluation fixtures."
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=DEFAULT_FIXTURE_ROOT,
        help=f"Fixture root directory (default: {DEFAULT_FIXTURE_ROOT})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate fixture YAML and corpus")
    validate_parser.set_defaults(func=run_validate)

    plan_parser = subparsers.add_parser("plan", help="Print planned query executions")
    plan_parser.add_argument("--json", action="store_true", help="Output query plan as JSON")
    plan_parser.set_defaults(func=run_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
