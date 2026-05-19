#!/usr/bin/env python3
"""
Search evaluation fixture loader and live HTTP evaluator.

The CLI validates the fixture corpus, prints query execution plans, and can run
the corpus against a PGVectorRAGIndexer HTTP API to produce JSON search-quality
results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
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


@dataclass(frozen=True)
class DocumentUpload:
    path: Path
    source_uri: str
    document_id: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "source_uri": self.source_uri,
            "document_id": self.document_id,
            "metadata": self.metadata,
        }


class SearchEvalHTTPError(RuntimeError):
    pass


class SearchEvalHTTPClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api/v1"
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = path if path.startswith(("http://", "https://")) else f"{self.api_base}{path}"
        kwargs.setdefault("timeout", self.timeout)
        response = self.session.request(method, url, **kwargs)
        if response.status_code >= 400:
            message = response.text[:500]
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = str(body.get("detail") or body.get("message") or body)
            except ValueError:
                pass
            raise SearchEvalHTTPError(f"{method} {url} failed ({response.status_code}): {message}")
        return response

    def health(self) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
        if response.status_code >= 400:
            raise SearchEvalHTTPError(
                f"GET {self.base_url}/health failed ({response.status_code}): {response.text[:500]}"
            )
        return response.json()

    def delete_document(self, document_id: str) -> str:
        url = f"{self.api_base}/documents/{document_id}"
        response = self.session.delete(url, timeout=self.timeout)
        if response.status_code == 404:
            return "missing"
        if response.status_code >= 400:
            raise SearchEvalHTTPError(
                f"DELETE {url} failed ({response.status_code}): {response.text[:500]}"
            )
        return "deleted"

    def upload_document(self, upload: DocumentUpload, force_reindex: bool = True) -> dict[str, Any]:
        with upload.path.open("rb") as handle:
            files = {"file": (upload.path.name, handle, _content_type_for_path(upload.path))}
            data = {
                "force_reindex": "true" if force_reindex else "false",
                "custom_source_uri": upload.source_uri,
                "metadata": json.dumps(upload.metadata, sort_keys=True),
            }
            response = self.request("POST", "/upload-and-index", files=files, data=data)
        return response.json()

    def search(self, plan: QueryPlan) -> dict[str, Any]:
        payload = {
            "query": plan.query,
            "top_k": plan.backend_top_k,
            "min_score": 0.0,
            "filters": plan.filters,
            "use_hybrid": True,
        }
        response = self.request("POST", "/search", json=payload)
        return response.json()


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
        if "first_expected_rank_lte" in assertions:
            try:
                first_rank_limit = int(assertions["first_expected_rank_lte"])
            except (TypeError, ValueError):
                errors.append(f"{query_id} assertion first_expected_rank_lte must be an integer")
            else:
                if first_rank_limit < 1:
                    errors.append(f"{query_id} assertion first_expected_rank_lte must be positive")
        if "literal_match_rank_lte" in assertions and not expected_files:
            errors.append(f"{query_id} assertion literal_match_rank_lte requires expected_files")
        if "literal_match_rank_lte" in assertions:
            try:
                literal_rank_limit = int(assertions["literal_match_rank_lte"])
            except (TypeError, ValueError):
                errors.append(f"{query_id} assertion literal_match_rank_lte must be an integer")
            else:
                if literal_rank_limit < 1:
                    errors.append(f"{query_id} assertion literal_match_rank_lte must be positive")
        if assertions.get("filters_respected") is True and not filters:
            errors.append(f"{query_id} assertion filters_respected requires filters")
        if "forbidden_at_5_eq" in assertions and not forbidden_files:
            errors.append(f"{query_id} assertion forbidden_at_5_eq requires forbidden_files")
        if "forbidden_at_5_eq" in assertions:
            try:
                forbidden_count = int(assertions["forbidden_at_5_eq"])
            except (TypeError, ValueError):
                errors.append(f"{query_id} assertion forbidden_at_5_eq must be an integer")
            else:
                if forbidden_count < 0:
                    errors.append(f"{query_id} assertion forbidden_at_5_eq must be non-negative")
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


def document_source_uri(fixture_set: FixtureSet, manifest_path: str) -> str:
    namespace = fixture_set.manifest["namespace"]
    return f"{namespace}/{manifest_path}"


def document_id_for_source_uri(source_uri: str) -> str:
    return hashlib.sha256(source_uri.encode("utf-8")).hexdigest()[:16]


def document_metadata(fixture_set: FixtureSet, document: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(fixture_set.manifest.get("default_metadata") or {})
    metadata.update(document.get("metadata") or {})
    metadata["eval_path"] = document["path"]
    if "type" not in metadata and metadata.get("doc_type"):
        metadata["type"] = metadata["doc_type"]
    return metadata


def build_document_uploads(fixture_set: FixtureSet) -> list[DocumentUpload]:
    uploads: list[DocumentUpload] = []
    for document in fixture_set.manifest.get("documents", []):
        manifest_path = document["path"]
        source_uri = document_source_uri(fixture_set, manifest_path)
        uploads.append(
            DocumentUpload(
                path=fixture_set.root / manifest_path,
                source_uri=source_uri,
                document_id=document_id_for_source_uri(source_uri),
                metadata=document_metadata(fixture_set, document),
            )
        )
    return uploads


def _content_type_for_path(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "text/markdown"
    if path.suffix.lower() == ".txt":
        return "text/plain"
    return "application/octet-stream"


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
    literal_hit_rank: int | None = None,
    literal_hit_found: bool | None = None,
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
        "LiteralHitFound": literal_hit_found,
        "LiteralHitRank": literal_hit_rank,
        "UniqueFiles@K": len(set(result_files)),
        "FilterViolations": filter_violations,
    }


def literal_query_tokens(query: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query)]


def text_contains_literal_tokens(text: str, tokens: list[str]) -> bool:
    haystack = text.lower()
    return bool(tokens) and all(token in haystack for token in tokens)


def calculate_literal_hit_rank(
    chunk_results: list[dict[str, Any]],
    file_results: list[dict[str, Any]],
    query_plan: QueryPlan,
    fixture_root: Path | None = None,
) -> int | None:
    return calculate_literal_hit_metrics(
        chunk_results,
        file_results,
        query_plan,
        fixture_root,
    )["LiteralHitRank"]


def calculate_literal_hit_metrics(
    chunk_results: list[dict[str, Any]],
    file_results: list[dict[str, Any]],
    query_plan: QueryPlan,
    fixture_root: Path | None = None,
) -> dict[str, bool | int | None]:
    tokens = literal_query_tokens(query_plan.query)
    if not tokens:
        return {"LiteralHitFound": None, "LiteralHitRank": None}

    literal_hit_sources = {
        normalize_result_path(str(result.get("source_uri", "")), fixture_root)
        for result in chunk_results
        if text_contains_literal_tokens(str(result.get("text_content", "")), tokens)
    }
    for index, result in enumerate(file_results[:query_plan.top_k_files], start=1):
        source_uri = normalize_result_path(str(result.get("source_uri", "")), fixture_root)
        if source_uri in literal_hit_sources:
            return {"LiteralHitFound": True, "LiteralHitRank": index}
    return {"LiteralHitFound": bool(literal_hit_sources), "LiteralHitRank": None}


def _assertion_severity(expected: Any) -> str:
    return "advisory" if str(expected).lower() == "advisory" else "required"


def _assertion_check(
    name: str,
    expected: Any,
    actual: Any,
    passed: bool | None,
    *,
    severity: str = "required",
    note: str | None = None,
) -> dict[str, Any]:
    status = "skipped"
    if passed is True:
        status = "pass"
    elif passed is False:
        status = "fail"

    check = {
        "name": name,
        "severity": severity,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "status": status,
    }
    if note:
        check["note"] = note
    return check


def evaluate_assertions(
    metrics: dict[str, Any],
    query_plan: QueryPlan,
    *,
    file_result_count: int | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    assertions = query_plan.assertions

    if "recall_at_5" in assertions:
        expected = assertions["recall_at_5"]
        severity = _assertion_severity(expected)
        actual = metrics.get("Recall@K")
        checks.append(
            _assertion_check(
                "recall_at_5",
                True,
                actual,
                actual is True,
                severity=severity,
            )
        )

    if "first_expected_rank_lte" in assertions:
        expected = int(assertions["first_expected_rank_lte"])
        actual = metrics.get("FirstExpectedRank")
        checks.append(
            _assertion_check(
                "first_expected_rank_lte",
                expected,
                actual,
                actual is not None and int(actual) <= expected,
            )
        )

    if "literal_match_rank_lte" in assertions:
        expected = int(assertions["literal_match_rank_lte"])
        actual = metrics.get("LiteralHitRank")
        checks.append(
            _assertion_check(
                "literal_match_rank_lte",
                expected,
                actual,
                actual is not None and int(actual) <= expected,
            )
        )

    if "filters_respected" in assertions:
        expected = assertions["filters_respected"]
        severity = _assertion_severity(expected)
        actual = metrics.get("FilterViolations")
        checks.append(
            _assertion_check(
                "filters_respected",
                0,
                actual,
                actual == 0,
                severity=severity,
            )
        )

    if "forbidden_at_5_eq" in assertions:
        expected = int(assertions["forbidden_at_5_eq"])
        actual = metrics.get("Forbidden@K")
        checks.append(
            _assertion_check(
                "forbidden_at_5_eq",
                expected,
                actual,
                actual == expected,
            )
        )

    if "min_unique_files_at_5" in assertions:
        expected = int(assertions["min_unique_files_at_5"])
        actual = metrics.get("UniqueFiles@K")
        checks.append(
            _assertion_check(
                "min_unique_files_at_5",
                expected,
                actual,
                actual is not None and int(actual) >= expected,
            )
        )

    if "no_confident_literal_match" in assertions:
        expected = assertions["no_confident_literal_match"]
        severity = _assertion_severity(expected)
        checks.append(
            _assertion_check(
                "no_confident_literal_match",
                0,
                file_result_count,
                None if file_result_count is None else file_result_count == 0,
                severity=severity,
                note="Current proxy is zero file results; score-confidence gating is not implemented yet.",
            )
        )

    required_failed = sum(
        1 for check in checks
        if check["severity"] == "required" and check["passed"] is False
    )
    advisory_failed = sum(
        1 for check in checks
        if check["severity"] == "advisory" and check["passed"] is False
    )
    skipped = sum(1 for check in checks if check["passed"] is None)
    return {
        "passed": required_failed == 0,
        "required_failed": required_failed,
        "advisory_failed": advisory_failed,
        "skipped": skipped,
        "checks": checks,
    }


def execute_query(client: SearchEvalHTTPClient, plan: QueryPlan, fixture_root: Path) -> dict[str, Any]:
    response = client.search(plan)
    chunk_results = list(response.get("results") or [])
    file_results = dedupe_chunks_by_source_uri(chunk_results)
    literal_hit_metrics = calculate_literal_hit_metrics(
        chunk_results,
        file_results,
        plan,
        fixture_root=fixture_root,
    )
    metrics = calculate_file_metrics(
        file_results,
        plan,
        fixture_root=fixture_root,
        literal_hit_rank=literal_hit_metrics["LiteralHitRank"],
        literal_hit_found=literal_hit_metrics["LiteralHitFound"],
    )
    return {
        "id": plan.id,
        "class": plan.query_class,
        "query": plan.query,
        "filters": plan.filters,
        "search_time_ms": response.get("search_time_ms"),
        "backend_result_count": len(chunk_results),
        "file_result_count": len(file_results),
        "metrics": metrics,
        "assertions": evaluate_assertions(metrics, plan, file_result_count=len(file_results)),
        "top_files": [
            normalize_result_path(str(result.get("source_uri", "")), fixture_root)
            for result in file_results[:plan.top_k_files]
        ],
    }


def cleanup_documents(client: SearchEvalHTTPClient, uploads: list[DocumentUpload]) -> dict[str, int]:
    summary = {"deleted": 0, "missing": 0}
    for upload in uploads:
        status = client.delete_document(upload.document_id)
        summary[status] = summary.get(status, 0) + 1
    return summary


def upload_documents(client: SearchEvalHTTPClient, uploads: list[DocumentUpload]) -> list[dict[str, Any]]:
    return [client.upload_document(upload, force_reindex=True) for upload in uploads]


def select_query_plans(plans: list[QueryPlan], query_ids: list[str] | None) -> list[QueryPlan]:
    if not query_ids:
        return plans
    requested = set(query_ids)
    selected = [plan for plan in plans if plan.id in requested]
    missing = sorted(requested - {plan.id for plan in selected})
    if missing:
        raise ValueError(f"Unknown query id(s): {', '.join(missing)}")
    return selected


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


def run_live(args: argparse.Namespace) -> int:
    fixture_set = load_fixture_set(args.fixture_root)
    errors = validate_fixture_set(fixture_set)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    try:
        plans = select_query_plans(build_query_plans(fixture_set), args.query_id)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    uploads = build_document_uploads(fixture_set)
    client = SearchEvalHTTPClient(
        base_url=args.api_base,
        api_key=args.api_key,
        timeout=args.timeout,
    )

    output: dict[str, Any] = {
        "api_base": args.api_base,
        "fixture_root": str(fixture_set.root),
        "documents": len(uploads),
        "queries": len(plans),
    }

    try:
        output["health"] = client.health()
        if not args.skip_cleanup:
            output["cleanup"] = cleanup_documents(client, uploads)
        if not args.skip_index:
            output["indexing"] = upload_documents(client, uploads)
        output["results"] = [
            execute_query(client, plan, fixture_set.root)
            for plan in plans
        ]
    except (requests.RequestException, SearchEvalHTTPError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.output_json:
        args.output_json.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Wrote {args.output_json}")
    else:
        print(json.dumps(output, indent=2, sort_keys=True))
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

    run_parser = subparsers.add_parser("run", help="Run the live HTTP search evaluation")
    run_parser.add_argument(
        "--api-base",
        default=os.environ.get("SEARCH_EVAL_API_BASE", "http://localhost:8000"),
        help="Base API URL before /api/v1 (default: http://localhost:8000)",
    )
    run_parser.add_argument(
        "--api-key",
        default=os.environ.get("PGVECTOR_API_KEY") or os.environ.get("API_KEY"),
        help="API key for authenticated servers; defaults to PGVECTOR_API_KEY or API_KEY",
    )
    run_parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds")
    run_parser.add_argument("--query-id", action="append", help="Run only a specific query id")
    run_parser.add_argument("--skip-cleanup", action="store_true", help="Do not delete prior eval docs first")
    run_parser.add_argument("--skip-index", action="store_true", help="Do not upload/index the corpus first")
    run_parser.add_argument("--output-json", type=Path, help="Write live evaluation result JSON to this path")
    run_parser.set_defaults(func=run_live)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
