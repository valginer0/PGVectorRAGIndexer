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
    args = build_arg_parser().parse_args(argv)
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
) -> dict[str, Any]:
    start = time.perf_counter()
    embedder = make_embedder(embedder_name, model_name=model_name)
    embedder_loaded_ms = elapsed_ms(start)

    with LocalLanceDBEngine(db_path, embedder=embedder) as engine:
        ingest_start = time.perf_counter()
        ingest_result = ingest_local_text_paths(engine, [corpus_dir], chunk_size=400)
        ingest_ms = elapsed_ms(ingest_start)

        query_outputs = []
        for query_spec in QUERIES:
            query_start = time.perf_counter()
            results, telemetry = engine.search_parent_child(
                query_spec["query"],
                parent_limit=1,
                child_limit=3,
            )
            query_ms = elapsed_ms(query_start)
            result_files = [Path(result.source_uri).name for result in results]
            matched_parent_files = [Path(source).name for source in telemetry.matched_parents]
            passed = result_files == [query_spec["expected_file"]]
            query_outputs.append(
                {
                    "id": query_spec["id"],
                    "query": query_spec["query"],
                    "expected_file": query_spec["expected_file"],
                    "result_files": result_files,
                    "matched_parent_files": matched_parent_files,
                    "query_ms": query_ms,
                    "passed": passed,
                }
            )

    skipped_reasons = [skipped.reason for skipped in ingest_result.skipped_files]
    passed = (
        ingest_result.indexed_documents == 2
        and skipped_reasons == ["unsupported_extension"]
        and all(item["passed"] for item in query_outputs)
    )
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


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def print_summary(output: dict[str, Any]) -> None:
    status = "PASS" if output["passed"] else "FAIL"
    print(f"{status}: local LanceDB desktop validation")
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


if __name__ == "__main__":
    raise SystemExit(main())
