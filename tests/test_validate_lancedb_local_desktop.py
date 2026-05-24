from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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
            {"id": "ev6", "passed": True, "result_files": ["ev6.txt"], "query_ms": 4.0}
        ],
        "total_ms": 20.0,
    })

    output = capsys.readouterr().out
    assert "Embedder        : hashing (1.5 ms)" in output
    assert "Total runtime   : 20.0 ms" in output
