import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "search_eval"
SEARCH_EVAL_PATH = REPO_ROOT / "scripts" / "search_eval.py"


def load_search_eval_module():
    spec = importlib.util.spec_from_file_location("search_eval", SEARCH_EVAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_fixture_set_and_build_query_plans():
    search_eval = load_search_eval_module()

    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    errors = search_eval.validate_fixture_set(fixture_set)
    plans = search_eval.build_query_plans(fixture_set)

    assert errors == []
    assert len(fixture_set.manifest_paths) == 12
    assert len(plans) == 19

    ev6_txt = next(plan for plan in plans if plan.id == "literal_ev6_txt")
    assert ev6_txt.filters == {
        "namespace": "search_eval_v0",
        "extensions": [".txt"],
    }
    assert ev6_txt.top_k_files == 5
    assert ev6_txt.backend_top_k == 100


def test_dedupe_chunks_by_source_uri_keeps_best_scored_chunk():
    search_eval = load_search_eval_module()

    deduped = search_eval.dedupe_chunks_by_source_uri(
        [
            {"source_uri": "a.txt", "chunk_index": 0, "relevance_score": 0.5},
            {"source_uri": "b.txt", "chunk_index": 0, "relevance_score": 0.7},
            {"source_uri": "a.txt", "chunk_index": 1, "relevance_score": 0.9},
        ]
    )

    assert [result["source_uri"] for result in deduped] == ["a.txt", "b.txt"]
    assert deduped[0]["chunk_index"] == 1


def test_calculate_file_metrics_for_filtered_literal_case():
    search_eval = load_search_eval_module()
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "literal_ev6_txt"
    )

    metrics = search_eval.calculate_file_metrics(
        [
            {
                "source_uri": str(FIXTURE_ROOT / "corpus" / "vehicles" / "ev6_owner_notes.txt"),
                "relevance_score": 0.9,
            },
            {
                "source_uri": str(FIXTURE_ROOT / "corpus" / "vehicles" / "ev6_battery_warranty.md"),
                "relevance_score": 0.8,
            },
            {
                "source_uri": str(FIXTURE_ROOT / "corpus" / "vehicles" / "ev6_chunk_crowding.txt"),
                "relevance_score": 0.7,
            },
        ],
        plan,
        fixture_root=FIXTURE_ROOT,
    )

    assert metrics["Recall@K"] is True
    assert metrics["MRR"] == 1.0
    assert metrics["FirstExpectedRank"] == 1
    assert metrics["Forbidden@K"] == 1
    assert metrics["FilterViolations"] == 1
    assert metrics["UniqueFiles@K"] == 3


def test_cli_validate_and_plan_smoke(capsys):
    search_eval = load_search_eval_module()

    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "validate"]) == 0
    validate_output = capsys.readouterr().out
    assert "12 documents" in validate_output
    assert "19 queries" in validate_output

    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "plan"]) == 0
    plan_output = capsys.readouterr().out
    assert "Query plan: 19 queries" in plan_output
    assert "literal_ev6_txt" in plan_output
