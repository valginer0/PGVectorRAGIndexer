from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip("lancedb")
pytest.importorskip("pyarrow")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_lancedb_local_desktop.py"


def load_validation_module():
    spec = importlib.util.spec_from_file_location("validate_lancedb_local_desktop", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_writes_local_lancedb_validation_json(tmp_path):
    validator = load_validation_module()
    output_path = tmp_path / "validation.json"

    status = validator.main([
        "--embedder", "hashing",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["passed"] is True
    assert output["embedder"]["mode"] == "hashing"
    assert output["ingestion"]["indexed_documents"] == 2
    assert output["ingestion"]["skipped_reasons"] == ["unsupported_extension"]
    assert [query["unique_result_files"] for query in output["queries"]] == [
        ["ev6_service.txt"],
        ["banana_recipe.md"],
    ]
    assert output["queries"][0]["result_files"] == ["ev6_service.txt"]


def test_main_accepts_query_manifest_and_retrieval_limits(tmp_path):
    validator = load_validation_module()
    output_path = tmp_path / "validation.json"
    manifest_path = tmp_path / "queries.json"
    manifest_path.write_text(
        json.dumps([
            {
                "id": "ev6_manifest",
                "query": "EV6 battery diagnostic",
                "expected_files": ["ev6_service.txt"],
                "allow_extra_results": True,
            }
        ]),
        encoding="utf-8",
    )

    status = validator.main([
        "--embedder", "hashing",
        "--queries-json", str(manifest_path),
        "--parent-limit", "1",
        "--child-limit", "4",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["passed"] is True
    assert output["retrieval"] == {"parent_limit": 1, "child_limit": 4}

    details = output["queries"][0]["matched_parent_details"][0]
    score_key = "rrf_score" if "rrf_score" in details else "fts_score"

    assert output["queries"][0] == {
        "id": "ev6_manifest",
        "query": "EV6 battery diagnostic",
        "expected_files": ["ev6_service.txt"],
        "allow_extra_results": True,
        "result_files": ["ev6_service.txt"],
        "unique_result_files": ["ev6_service.txt"],
        "matched_parent_files": ["ev6_service.txt"],
        "matched_parent_details": [
            {
                "rank": 1,
                "source_uri": details["source_uri"],
                score_key: details[score_key],
                "relative_path": "ev6_service.txt",
                "file_name": "ev6_service.txt",
            }
        ],
        "missing_expected_files": [],
        "unexpected_files": [],
        "query_ms": output["queries"][0]["query_ms"],
        "passed": True,
    }
    assert isinstance(details[score_key], float)


def test_load_query_specs_rejects_invalid_manifest(tmp_path):
    validator = load_validation_module()
    manifest_path = tmp_path / "queries.json"
    manifest_path.write_text(json.dumps([{"id": "missing_query"}]), encoding="utf-8")

    with pytest.raises(SystemExit, match="non-empty string query"):
        validator.load_query_specs(manifest_path)


def test_expected_files_normalize_windows_separators():
    validator = load_validation_module()

    assert validator.expected_files_for_query({
        "expected_files": [r"docs\api\README.md", "./guide/index.md"]
    }) == [
        "docs/api/README.md",
        "guide/index.md",
    ]


def test_validate_expected_files_exist_rejects_missing_file(tmp_path):
    validator = load_validation_module()
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    query_specs = [
        {
            "id": "missing",
            "query": "missing file",
            "expected_files": ["docs/missing.md"],
        }
    ]

    with pytest.raises(SystemExit, match="Expected files were not found"):
        validator.validate_expected_files_exist(query_specs, corpus_dir)


def test_validate_expected_files_exist_rejects_path_escape(tmp_path):
    validator = load_validation_module()
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    query_specs = [
        {
            "id": "escape",
            "query": "escape file",
            "expected_files": ["../outside.md"],
        }
    ]

    with pytest.raises(SystemExit, match="Expected files must stay inside"):
        validator.validate_expected_files_exist(query_specs, corpus_dir)


def test_display_path_for_source_uses_corpus_relative_path(tmp_path):
    validator = load_validation_module()
    corpus_dir = tmp_path / "corpus"
    source = corpus_dir / "docs" / "api" / "README.md"
    source.parent.mkdir(parents=True)
    source.write_text("API docs", encoding="utf-8")

    assert validator.display_path_for_source(str(source), corpus_dir) == "docs/api/README.md"


def test_dedupe_preserving_order_keeps_first_file_occurrence():
    validator = load_validation_module()

    assert validator.dedupe_preserving_order(["a.txt", "a.txt", "b.txt", "a.txt"]) == [
        "a.txt",
        "b.txt",
    ]


def test_print_summary_includes_timing_fields(capsys):
    validator = load_validation_module()

    validator.print_summary({
        "passed": True,
        "embedder": {"mode": "hashing", "load_ms": 1.5},
        "ingestion": {"indexed_documents": 2, "chunk_count": 3, "ingest_ms": 12.0},
        "queries": [
            {
                "id": "ev6",
                "passed": True,
                "result_files": ["ev6.txt"],
                "matched_parent_details": [
                    {"file_name": "ev6.txt", "rank": 1, "fts_score": 6.3717}
                ],
                "query_ms": 4.0,
            }
        ],
        "total_ms": 20.0,
    })

    output = capsys.readouterr().out
    assert "Embedder        : hashing (1.5 ms)" in output
    assert "top parent: ev6.txt (score: 6.3717)" in output
    assert "Total runtime   : 20.0 ms" in output


def test_top_parent_summary_handles_missing_score():
    validator = load_validation_module()

    assert validator.top_parent_summary({
        "matched_parent_details": [
            {"source_uri": "/docs/invoice_4421.txt", "rank": 1, "fts_score": None}
        ]
    }) == "invoice_4421.txt (score: n/a)"
