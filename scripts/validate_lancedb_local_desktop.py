#!/usr/bin/env python3
"""Validate the off-by-default local LanceDB desktop search path.

This script creates a tiny local text corpus, builds a LanceDB index through the
same UI-free ingestion adapter used by the desktop, runs parent-child searches,
and writes a JSON result that can be attached to branch validation notes.

Recommended native Windows run:

  .\\venv\\Scripts\\python.exe scripts\\validate_lancedb_local_desktop.py ^
    --output-json docs\\internal\\LANCEDB_LOCAL_DESKTOP_VALIDATION.json

Use ``--embedder hashing`` for a fast structural smoke test that does not load
the sentence-transformers model. Use the default ``sentence-transformer`` mode
for the real desktop validation gate.

For larger local-folder validation, pass ``--corpus-dir`` with ``--queries-json``.
The query manifest is a JSON list of objects:

  [
    {
      "id": "ev6_battery",
      "query": "EV6 battery diagnostic",
      "expected_files": ["ev6_service.txt"],
      "allow_extra_results": true
    }
  ]
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop_app.lancedb_engine import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    HashingEmbedder,
    LocalLanceDBEngine,
    SentenceTransformerEmbedder,
)
from desktop_app.lancedb_ingestion import ingest_local_text_paths  # noqa: E402


QUERIES = [
    {
        "id": "ev6_battery",
        "query": "EV6 battery diagnostic",
        "expected_file": "ev6_service.txt",
    },
    {
        "id": "banana_recipe",
        "query": "banana recipe",
        "expected_file": "banana_recipe.md",
    },
]


def default_query_specs() -> list[dict[str, Any]]:
    return [dict(query_spec) for query_spec in QUERIES]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        help="LanceDB index directory. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        help="Corpus directory. If omitted, a tiny validation corpus is created.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Optional path for JSON validation output.",
    )
    parser.add_argument(
        "--queries-json",
        type=Path,
        help="Optional JSON query manifest for validating an existing corpus.",
    )
    parser.add_argument(
        "--parent-limit",
        type=int,
        default=1,
        help="Number of parent documents to retrieve per query.",
    )
    parser.add_argument(
        "--child-limit",
        type=int,
        default=3,
        help="Number of child chunks to return per query.",
    )
    parser.add_argument(
        "--embedder",
        choices=("sentence-transformer", "hashing"),
        default="sentence-transformer",
        help="Embedding provider to use for validation.",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Sentence-transformers model name for --embedder sentence-transformer.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep temporary corpus/index directories after the run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.parent_limit < 1:
        parser.error("--parent-limit must be at least 1")
    if args.child_limit < 1:
        parser.error("--child-limit must be at least 1")
    query_specs = load_query_specs(args.queries_json) if args.queries_json else default_query_specs()
    temp_dir = Path(tempfile.mkdtemp(prefix="lancedb_local_desktop_"))
    created_temp = True
    try:
        corpus_dir = args.corpus_dir or temp_dir / "corpus"
        db_path = args.db_path or temp_dir / "lancedb"
        if args.corpus_dir is None:
            create_validation_corpus(corpus_dir)
        if db_path.exists():
            shutil.rmtree(db_path)

        output = run_validation(
            corpus_dir=corpus_dir,
            db_path=db_path,
            embedder_name=args.embedder,
            model_name=args.model_name,
            query_specs=query_specs,
            parent_limit=args.parent_limit,
            child_limit=args.child_limit,
        )
        output["temp_root"] = str(temp_dir) if args.keep else None

        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json.dumps(output, indent=2), encoding="utf-8")

        print_summary(output)
        return 0 if output["passed"] else 1
    finally:
        if created_temp and not args.keep:
            shutil.rmtree(temp_dir, ignore_errors=True)


def create_validation_corpus(corpus_dir: Path) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "ev6_service.txt").write_text(
        "EV6 high voltage battery diagnostic notes and charging service procedure.",
        encoding="utf-8",
    )
    (corpus_dir / "banana_recipe.md").write_text(
        "Banana bread recipe with cinnamon and walnuts.",
        encoding="utf-8",
    )
    (corpus_dir / "ignored.png").write_text(
        "EV6 text in an unsupported file should not be indexed.",
        encoding="utf-8",
    )


def run_validation(
    *,
    corpus_dir: Path,
    db_path: Path,
    embedder_name: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    query_specs: list[dict[str, Any]] | None = None,
    parent_limit: int = 1,
    child_limit: int = 3,
) -> dict[str, Any]:
    if query_specs is None:
        query_specs = default_query_specs()

    start = time.perf_counter()
    embedder = make_embedder(embedder_name, model_name=model_name)
    embedder_loaded_ms = elapsed_ms(start)

    with LocalLanceDBEngine(db_path, embedder=embedder) as engine:
        ingest_start = time.perf_counter()
        ingest_result = ingest_local_text_paths(engine, [corpus_dir], chunk_size=400)
        ingest_ms = elapsed_ms(ingest_start)

        query_outputs = []
        for query_spec in query_specs:
            query_start = time.perf_counter()
            results, telemetry = engine.search_parent_child(
                query_spec["query"],
                parent_limit=parent_limit,
                child_limit=child_limit,
            )
            query_ms = elapsed_ms(query_start)
            result_files = [Path(result.source_uri).name for result in results]
            unique_result_files = dedupe_preserving_order(result_files)
            matched_parent_files = [Path(source).name for source in telemetry.matched_parents]
            expected_files = expected_files_for_query(query_spec)
            allow_extra_results = bool(query_spec.get("allow_extra_results", False))
            missing_expected_files = [
                expected_file
                for expected_file in expected_files
                if expected_file not in unique_result_files
            ]
            unexpected_files = [
                result_file
                for result_file in unique_result_files
                if result_file not in expected_files
            ]
            passed = (
                not missing_expected_files
                and (allow_extra_results or not unexpected_files)
            )
            query_outputs.append(
                {
                    "id": query_spec["id"],
                    "query": query_spec["query"],
                    "expected_files": expected_files,
                    "allow_extra_results": allow_extra_results,
                    "result_files": result_files,
                    "unique_result_files": unique_result_files,
                    "matched_parent_files": matched_parent_files,
                    "missing_expected_files": missing_expected_files,
                    "unexpected_files": unexpected_files,
                    "query_ms": query_ms,
                    "passed": passed,
                }
            )

    skipped_reasons = [skipped.reason for skipped in ingest_result.skipped_files]
    using_default_corpus = query_specs == default_query_specs()
    ingestion_passed = True
    if using_default_corpus:
        ingestion_passed = (
            ingest_result.indexed_documents == 2
            and skipped_reasons == ["unsupported_extension"]
        )
    passed = ingestion_passed and all(item["passed"] for item in query_outputs)
    return {
        "passed": passed,
        "environment": environment_info(),
        "embedder": {
            "mode": embedder_name,
            "model_name": model_name if embedder_name == "sentence-transformer" else None,
            "load_ms": embedder_loaded_ms,
        },
        "paths": {
            "corpus_dir": str(corpus_dir),
            "db_path": str(db_path),
        },
        "retrieval": {
            "parent_limit": parent_limit,
            "child_limit": child_limit,
        },
        "ingestion": {
            "indexed_documents": ingest_result.indexed_documents,
            "source_count": ingest_result.stats.source_count,
            "chunk_count": ingest_result.stats.chunk_count,
            "skipped_reasons": skipped_reasons,
            "ingest_ms": ingest_ms,
        },
        "queries": query_outputs,
        "total_ms": elapsed_ms(start),
    }


def load_query_specs(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --queries-json: {exc}") from exc

    if not isinstance(raw, list):
        raise SystemExit("--queries-json must contain a JSON list")
    if not raw:
        raise SystemExit("--queries-json must contain at least one query")

    query_specs = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"Query #{index} must be an object")
        query_id = item.get("id")
        query_text = item.get("query")
        if not isinstance(query_id, str) or not query_id.strip():
            raise SystemExit(f"Query #{index} must include a non-empty string id")
        if not isinstance(query_text, str) or not query_text.strip():
            raise SystemExit(f"Query {query_id!r} must include a non-empty string query")
        expected_files = expected_files_for_query(item)
        if not expected_files:
            raise SystemExit(f"Query {query_id!r} must include expected_file or expected_files")
        query_specs.append(
            {
                "id": query_id,
                "query": query_text,
                "expected_files": expected_files,
                "allow_extra_results": bool(item.get("allow_extra_results", False)),
            }
        )
    return query_specs


def expected_files_for_query(query_spec: dict[str, Any]) -> list[str]:
    if "expected_files" in query_spec:
        expected_files = query_spec["expected_files"]
        if not isinstance(expected_files, list) or not all(
            isinstance(value, str) and value for value in expected_files
        ):
            raise SystemExit("expected_files must be a non-empty list of strings")
        return list(expected_files)
    expected_file = query_spec.get("expected_file")
    if isinstance(expected_file, str) and expected_file:
        return [expected_file]
    return []


def make_embedder(embedder_name: str, *, model_name: str):
    if embedder_name == "hashing":
        return HashingEmbedder()
    if embedder_name == "sentence-transformer":
        return SentenceTransformerEmbedder(model_name=model_name)
    raise ValueError(f"Unsupported embedder: {embedder_name}")


def environment_info() -> dict[str, str]:
    try:
        import lancedb

        lancedb_version = lancedb.__version__
    except Exception:
        lancedb_version = "unknown"
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "lancedb": lancedb_version,
    }


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def print_summary(output: dict[str, Any]) -> None:
    status = "PASS" if output["passed"] else "FAIL"
    print(f"{status}: local LanceDB desktop validation")
    print(
        f"Embedder        : {output['embedder']['mode']} "
        f"({output['embedder']['load_ms']} ms)"
    )
    print(
        "Indexed "
        f"{output['ingestion']['indexed_documents']} documents, "
        f"{output['ingestion']['chunk_count']} chunks "
        f"in {output['ingestion']['ingest_ms']} ms"
    )
    for query in output["queries"]:
        query_status = "PASS" if query["passed"] else "FAIL"
        print(
            f"{query_status}: {query['id']} -> "
            f"{query['result_files']} ({query['query_ms']} ms)"
        )
    print(f"Total runtime   : {output['total_ms']} ms")


if __name__ == "__main__":
    raise SystemExit(main())
