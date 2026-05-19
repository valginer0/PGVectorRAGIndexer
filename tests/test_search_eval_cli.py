import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "search_eval"
SEARCH_EVAL_PATH = REPO_ROOT / "scripts" / "search_eval.py"


def load_search_eval_module():
    spec = importlib.util.spec_from_file_location("search_eval", SEARCH_EVAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def search_eval():
    return load_search_eval_module()


def test_validate_fixture_set_and_build_query_plans(search_eval):
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


def test_dedupe_chunks_by_source_uri_keeps_best_scored_chunk(search_eval):
    deduped = search_eval.dedupe_chunks_by_source_uri(
        [
            {"source_uri": "a.txt", "chunk_index": 0, "relevance_score": 0.5},
            {"source_uri": "b.txt", "chunk_index": 0, "relevance_score": 0.7},
            {"source_uri": "a.txt", "chunk_index": 1, "relevance_score": 0.9},
        ]
    )

    assert [result["source_uri"] for result in deduped] == ["a.txt", "b.txt"]
    assert deduped[0]["chunk_index"] == 1


def test_calculate_file_metrics_for_filtered_literal_case(search_eval):
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


def test_evaluate_assertions_reports_required_and_advisory_failures(search_eval):
    plan = search_eval.QueryPlan(
        id="assertion_probe",
        query_class="negative",
        query="EV6",
        filters={"namespace": "search_eval_v0", "extensions": [".txt"]},
        expected_files=["corpus/vehicles/ev6_owner_notes.txt"],
        relevant_files=["corpus/vehicles/ev6_owner_notes.txt"],
        forbidden_files=["corpus/noise/banana_bread_recipe.txt"],
        assertions={
            "recall_at_5": True,
            "first_expected_rank_lte": 2,
            "literal_match_rank_lte": 2,
            "filters_respected": True,
            "forbidden_at_5_eq": 0,
            "min_unique_files_at_5": 2,
            "no_confident_literal_match": "advisory",
        },
        top_k_files=5,
        backend_top_k=100,
    )
    metrics = {
        "Recall@K": True,
        "MRR": 1.0,
        "Precision@K": 0.5,
        "Forbidden@K": 1,
        "FirstExpectedRank": 1,
        "UniqueFiles@K": 3,
        "FilterViolations": 0,
    }

    assertions = search_eval.evaluate_assertions(metrics, plan, file_result_count=3)
    checks = {check["name"]: check for check in assertions["checks"]}

    assert assertions["passed"] is False
    assert assertions["required_failed"] == 1
    assert assertions["advisory_failed"] == 1
    assert assertions["skipped"] == 1
    assert checks["forbidden_at_5_eq"]["status"] == "fail"
    assert checks["no_confident_literal_match"]["severity"] == "advisory"
    assert checks["no_confident_literal_match"]["status"] == "fail"
    assert checks["literal_match_rank_lte"]["status"] == "skipped"


def test_build_document_uploads_adds_eval_metadata_and_stable_ids(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    uploads = search_eval.build_document_uploads(fixture_set)

    owner_notes = next(
        upload for upload in uploads
        if upload.source_uri == "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt"
    )

    assert len(uploads) == 12
    assert owner_notes.path == FIXTURE_ROOT / "corpus/vehicles/ev6_owner_notes.txt"
    assert owner_notes.document_id == search_eval.document_id_for_source_uri(owner_notes.source_uri)
    assert owner_notes.metadata["namespace"] == "search_eval_v0"
    assert owner_notes.metadata["category"] == "search_eval"
    assert owner_notes.metadata["doc_type"] == "owner_notes"
    assert owner_notes.metadata["type"] == "owner_notes"
    assert owner_notes.metadata["eval_path"] == "corpus/vehicles/ev6_owner_notes.txt"


def test_validate_fixture_set_rejects_unsatisfiable_assertions(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    invalid_query = dict(fixture_set.query_items[0])
    invalid_query["id"] = "invalid_recall_gate"
    invalid_query["expected_files"] = []
    invalid_query["assertions"] = {"recall_at_5": True}
    invalid_unique_query = dict(fixture_set.query_items[0])
    invalid_unique_query["id"] = "invalid_unique_gate"
    invalid_unique_query["assertions"] = {"min_unique_files_at_5": "many"}
    invalid_queries = dict(fixture_set.queries)
    invalid_queries["queries"] = [invalid_query, invalid_unique_query]

    invalid_fixture_set = search_eval.FixtureSet(
        root=fixture_set.root,
        manifest=fixture_set.manifest,
        queries=invalid_queries,
    )

    errors = search_eval.validate_fixture_set(invalid_fixture_set)

    assert "invalid_recall_gate assertion recall_at_5 requires expected_files" in errors
    assert "invalid_unique_gate assertion min_unique_files_at_5 must be an integer" in errors


def test_cli_run_uses_http_client_and_writes_json(search_eval, monkeypatch, tmp_path):
    class FakeHTTPClient:
        def __init__(self, base_url, api_key=None, timeout=120.0):
            self.base_url = base_url
            self.api_key = api_key
            self.timeout = timeout

        def health(self):
            return {"status": "healthy"}

        def delete_document(self, _document_id):
            return "missing"

        def upload_document(self, upload, force_reindex=True):
            assert force_reindex is True
            assert upload.metadata["namespace"] == "search_eval_v0"
            return {
                "status": "success",
                "document_id": upload.document_id,
                "source_uri": upload.source_uri,
                "chunks_indexed": 1,
            }

        def search(self, plan):
            assert plan.id == "literal_ev6_txt"
            return {
                "search_time_ms": 12.3,
                "results": [
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
                        "relevance_score": 0.9,
                    },
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_chunk_crowding.txt",
                        "relevance_score": 0.8,
                    },
                ],
            }

    monkeypatch.setattr(search_eval, "SearchEvalHTTPClient", FakeHTTPClient)
    output_path = tmp_path / "result.json"

    status = search_eval.main([
        "--fixture-root", str(FIXTURE_ROOT),
        "run",
        "--api-base", "http://example.test",
        "--query-id", "literal_ev6_txt",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text())
    assert output["api_base"] == "http://example.test"
    assert output["cleanup"] == {"deleted": 0, "missing": 12}
    assert len(output["indexing"]) == 12
    assert output["results"][0]["metrics"]["Recall@K"] is True
    assert output["results"][0]["assertions"]["passed"] is True
    assert output["results"][0]["assertions"]["skipped"] == 1
    assert output["results"][0]["top_files"] == [
        "corpus/vehicles/ev6_owner_notes.txt",
        "corpus/vehicles/ev6_chunk_crowding.txt",
    ]


def test_cli_validate_and_plan_smoke(search_eval, capsys):
    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "validate"]) == 0
    validate_output = capsys.readouterr().out
    assert "12 documents" in validate_output
    assert "19 queries" in validate_output

    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "plan"]) == 0
    plan_output = capsys.readouterr().out
    assert "Query plan: 19 queries" in plan_output
    assert "literal_ev6_txt" in plan_output
