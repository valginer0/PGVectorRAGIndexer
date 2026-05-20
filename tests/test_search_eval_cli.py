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


def test_result_score_prefers_rank_score(search_eval):
    assert search_eval._result_score({
        "rank_score": 10.5,
        "relevance_score": 0.1,
    }) == 10.5


def test_identifier_query_tokens_finds_product_shaped_identifiers(search_eval):
    assert search_eval.identifier_query_tokens("EV6 fast charging limit") == ["ev6"]
    assert search_eval.identifier_query_tokens("invoice #4421") == ["4421"]
    assert search_eval.identifier_query_tokens("JWT session timeout policy") == ["jwt"]
    assert search_eval.identifier_query_tokens("ZXQ-000-NOT-REAL") == ["zxq-000-not-real"]
    assert search_eval.identifier_query_tokens("customer payment issue") == []
    assert search_eval.identifier_query_tokens("I have a question") == []


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
        literal_hit_rank=1,
        literal_hit_found=True,
        literal_hit_tokens=["ev6"],
    )

    assert metrics["Recall@K"] is True
    assert metrics["MRR"] == 1.0
    assert metrics["FirstExpectedRank"] == 1
    assert metrics["LiteralHitFound"] is True
    assert metrics["LiteralHitRank"] == 1
    assert metrics["LiteralHitTokens"] == ["ev6"]
    assert metrics["Forbidden@K"] == 1
    assert metrics["FilterViolations"] == 1
    assert metrics["UniqueFiles@K"] == 3


def test_calculate_literal_hit_rank_uses_any_chunk_for_displayed_file(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "literal_ev6_txt"
    )
    displayed = [
        {"source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt", "relevance_score": 0.9},
        {"source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt", "relevance_score": 0.8},
    ]
    chunks = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "General notes without the identifier.",
            "relevance_score": 0.9,
        },
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "The EV6 owner notes include a direct identifier hit.",
            "relevance_score": 0.2,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "text_content": "No vehicle code here.",
            "relevance_score": 0.8,
        },
    ]

    assert search_eval.calculate_literal_hit_rank(chunks, displayed, plan, FIXTURE_ROOT) == 1


def test_calculate_literal_hit_metrics_distinguishes_found_outside_top_k(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    original = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "literal_ev6_txt"
    )
    plan = search_eval.QueryPlan(
        id=original.id,
        query_class=original.query_class,
        query=original.query,
        filters=original.filters,
        expected_files=original.expected_files,
        relevant_files=original.relevant_files,
        forbidden_files=original.forbidden_files,
        assertions=original.assertions,
        top_k_files=1,
        backend_top_k=original.backend_top_k,
    )
    file_results = [
        {"source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt", "relevance_score": 0.9},
        {"source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt", "relevance_score": 0.1},
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "The EV6 identifier is present, but below the displayed cutoff.",
            "relevance_score": 0.1,
        }
    ]

    metrics = search_eval.calculate_literal_hit_metrics(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
    )

    assert metrics == {
        "LiteralHitFound": True,
        "LiteralHitRank": None,
        "LiteralHitTokens": ["ev6"],
    }


def test_literal_match_tokens_override_query_tokens(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    original = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "hybrid_ev6_charging"
    )

    assert search_eval.literal_match_tokens_for_plan(original) == ["ev6"]

    full_query_plan = search_eval.QueryPlan(
        id=original.id,
        query_class=original.query_class,
        query=original.query,
        filters=original.filters,
        expected_files=original.expected_files,
        relevant_files=original.relevant_files,
        forbidden_files=original.forbidden_files,
        assertions={"literal_match_rank_lte": 2},
        top_k_files=original.top_k_files,
        backend_top_k=original.backend_top_k,
    )
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "The EV6 owner notes mention fast charging but not the full query.",
            "rank_score": 10.0,
        }
    ]
    file_results = [{"source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt"}]

    assert search_eval.calculate_literal_hit_metrics(
        chunk_results,
        file_results,
        original,
        FIXTURE_ROOT,
    ) == {"LiteralHitFound": True, "LiteralHitRank": 1, "LiteralHitTokens": ["ev6"]}
    assert search_eval.calculate_literal_hit_metrics(
        chunk_results,
        file_results,
        full_query_plan,
        FIXTURE_ROOT,
    ) == {
        "LiteralHitFound": False,
        "LiteralHitRank": None,
        "LiteralHitTokens": ["ev6", "fast", "charging", "limit"],
    }


def test_build_top_file_details_adds_diagnostic_flags(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "literal_ev6_txt"
    )
    file_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "chunk_index": 2,
            "relevance_score": 0.91,
            "rank_score": 10.91,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "chunk_index": 0,
            "relevance_score": 0.42,
            "rank_score": 0.42,
        },
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "A lower-ranked chunk mentions EV6 directly.",
            "relevance_score": 0.1,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "text_content": "Banana notes without the vehicle identifier.",
            "relevance_score": 0.42,
        },
    ]

    details = search_eval.build_top_file_details(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
    )

    assert details[0] == {
        "rank": 1,
        "source_uri": "corpus/vehicles/ev6_owner_notes.txt",
        "score": 10.91,
        "rank_score": 10.91,
        "relevance_score": 0.91,
        "chunk_index": 2,
        "literal_hit": True,
        "expected": True,
        "relevant": True,
        "forbidden": False,
    }
    assert details[1]["source_uri"] == "corpus/noise/banana_bread_recipe.txt"
    assert details[1]["literal_hit"] is False
    assert details[1]["forbidden"] is True


def test_literal_tail_suppression_filters_low_score_non_literal_files(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "literal_ev6_txt"
    )
    file_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "rank_score": 10.91,
            "relevance_score": 0.91,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "rank_score": 0.06,
            "relevance_score": 0.42,
        },
        {
            "source_uri": "search_eval_v0/corpus/vehicles/charging_overview.txt",
            "rank_score": 0.2,
            "relevance_score": 0.2,
        },
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
            "text_content": "The EV6 owner notes include a direct hit.",
            "rank_score": 10.91,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "text_content": "Banana notes without the vehicle identifier.",
            "rank_score": 0.06,
        },
        {
            "source_uri": "search_eval_v0/corpus/vehicles/charging_overview.txt",
            "text_content": "General charging overview.",
            "rank_score": 0.2,
        },
    ]

    filtered, diagnostics = search_eval.apply_literal_tail_suppression(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
        search_eval.LiteralTailSuppressionConfig(
            anchor_threshold=10.0,
            tail_threshold=0.1,
        ),
    )

    assert diagnostics["active"] is True
    assert diagnostics["reason"] == "strong_literal_hit"
    assert diagnostics["suppressed_count"] == 1
    assert diagnostics["suppressed_top_k_count"] == 1
    assert diagnostics["suppressed_preview"][0]["source_uri"] == "corpus/noise/banana_bread_recipe.txt"
    assert [result["source_uri"] for result in filtered] == [
        "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
        "search_eval_v0/corpus/vehicles/charging_overview.txt",
    ]


def test_literal_tail_suppression_skips_contextual_classes(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "context_auth_timeout"
    )
    file_results = [
        {
            "source_uri": "search_eval_v0/corpus/engineering/auth_session_policy.txt",
            "rank_score": 10.91,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "rank_score": 0.01,
        },
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/engineering/auth_session_policy.txt",
            "text_content": "Session timeout context appears directly.",
            "rank_score": 10.91,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "text_content": "Banana notes.",
            "rank_score": 0.01,
        },
    ]

    filtered, diagnostics = search_eval.apply_literal_tail_suppression(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
        search_eval.LiteralTailSuppressionConfig(
            anchor_threshold=10.0,
            tail_threshold=0.1,
        ),
    )

    assert diagnostics["active"] is False
    assert diagnostics["reason"] == "ineligible_query_class"
    assert filtered == file_results


def test_literal_tail_suppression_identifier_signal_does_not_need_query_class(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "hybrid_ev6_battery_warranty"
    )
    file_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_battery_warranty.md",
            "rank_score": 11.0,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "rank_score": 0.04,
        },
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/vehicles/ev6_battery_warranty.md",
            "text_content": "The EV6 battery warranty has direct identifier coverage.",
            "rank_score": 11.0,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
            "text_content": "Banana notes.",
            "rank_score": 0.04,
        },
    ]

    filtered, diagnostics = search_eval.apply_literal_tail_suppression(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
        search_eval.LiteralTailSuppressionConfig(
            anchor_threshold=10.0,
            tail_threshold=0.1,
            signal="identifier-token",
        ),
    )

    assert diagnostics["active"] is True
    assert diagnostics["signal"] == "identifier-token"
    assert diagnostics["literal_hit_tokens"] == ["ev6"]
    assert diagnostics["suppressed_count"] == 1
    assert filtered == [file_results[0]]


def test_literal_tail_suppression_identifier_signal_skips_plain_language(search_eval):
    fixture_set = search_eval.load_fixture_set(FIXTURE_ROOT)
    plan = next(
        item for item in search_eval.build_query_plans(fixture_set)
        if item.id == "filter_billing_md"
    )
    file_results = [
        {
            "source_uri": "search_eval_v0/corpus/finance/billing_policy.md",
            "rank_score": 11.0,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/random_meeting_notes.md",
            "rank_score": 0.04,
        },
    ]
    chunk_results = [
        {
            "source_uri": "search_eval_v0/corpus/finance/billing_policy.md",
            "text_content": "Customer payment issue policy.",
            "rank_score": 11.0,
        },
        {
            "source_uri": "search_eval_v0/corpus/noise/random_meeting_notes.md",
            "text_content": "Meeting notes.",
            "rank_score": 0.04,
        },
    ]

    filtered, diagnostics = search_eval.apply_literal_tail_suppression(
        chunk_results,
        file_results,
        plan,
        FIXTURE_ROOT,
        search_eval.LiteralTailSuppressionConfig(
            anchor_threshold=10.0,
            tail_threshold=0.1,
            signal="identifier-token",
        ),
    )

    assert diagnostics["active"] is False
    assert diagnostics["reason"] == "no_identifier_tokens"
    assert filtered == file_results


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
        "LiteralHitFound": True,
        "LiteralHitRank": 1,
        "UniqueFiles@K": 3,
        "FilterViolations": 0,
    }

    assertions = search_eval.evaluate_assertions(metrics, plan)
    checks = {check["name"]: check for check in assertions["checks"]}

    assert assertions["passed"] is False
    assert assertions["required_failed"] == 1
    assert assertions["advisory_failed"] == 1
    assert assertions["skipped"] == 0
    assert checks["forbidden_at_5_eq"]["status"] == "fail"
    assert checks["no_confident_literal_match"]["severity"] == "advisory"
    assert checks["no_confident_literal_match"]["status"] == "fail"
    assert checks["no_confident_literal_match"]["actual"] is True
    assert checks["literal_match_rank_lte"]["status"] == "pass"


def test_no_confident_literal_match_passes_when_literal_tokens_absent(search_eval):
    plan = search_eval.QueryPlan(
        id="unknown_identifier_probe",
        query_class="negative",
        query="ZXQ-000-NOT-REAL",
        filters={"namespace": "search_eval_v0"},
        expected_files=[],
        relevant_files=[],
        forbidden_files=[],
        assertions={"no_confident_literal_match": "advisory"},
        top_k_files=5,
        backend_top_k=100,
    )
    metrics = {
        "Recall@K": False,
        "MRR": 0.0,
        "Precision@K": 0.0,
        "Forbidden@K": 0,
        "FirstExpectedRank": None,
        "LiteralHitFound": False,
        "LiteralHitRank": None,
        "UniqueFiles@K": 5,
        "FilterViolations": 0,
    }

    assertions = search_eval.evaluate_assertions(metrics, plan)
    checks = {check["name"]: check for check in assertions["checks"]}

    assert assertions["passed"] is True
    assert assertions["required_failed"] == 0
    assert assertions["advisory_failed"] == 0
    assert checks["no_confident_literal_match"]["status"] == "pass"
    assert checks["no_confident_literal_match"]["expected"] is False
    assert checks["no_confident_literal_match"]["actual"] is False


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
    invalid_first_rank_query = dict(fixture_set.query_items[0])
    invalid_first_rank_query["id"] = "invalid_first_rank_gate"
    invalid_first_rank_query["assertions"] = {"first_expected_rank_lte": "near"}
    invalid_literal_rank_query = dict(fixture_set.query_items[0])
    invalid_literal_rank_query["id"] = "invalid_literal_rank_gate"
    invalid_literal_rank_query["assertions"] = {"literal_match_rank_lte": 0}
    invalid_literal_tokens_query = dict(fixture_set.query_items[0])
    invalid_literal_tokens_query["id"] = "invalid_literal_tokens_gate"
    invalid_literal_tokens_query["assertions"] = {"literal_match_tokens": []}
    invalid_forbidden_query = dict(fixture_set.query_items[0])
    invalid_forbidden_query["id"] = "invalid_forbidden_gate"
    invalid_forbidden_query["assertions"] = {"forbidden_at_5_eq": -1}
    invalid_unique_query = dict(fixture_set.query_items[0])
    invalid_unique_query["id"] = "invalid_unique_gate"
    invalid_unique_query["assertions"] = {"min_unique_files_at_5": "many"}
    invalid_queries = dict(fixture_set.queries)
    invalid_queries["queries"] = [
        invalid_query,
        invalid_first_rank_query,
        invalid_literal_rank_query,
        invalid_literal_tokens_query,
        invalid_forbidden_query,
        invalid_unique_query,
    ]

    invalid_fixture_set = search_eval.FixtureSet(
        root=fixture_set.root,
        manifest=fixture_set.manifest,
        queries=invalid_queries,
    )

    errors = search_eval.validate_fixture_set(invalid_fixture_set)

    assert "invalid_recall_gate assertion recall_at_5 requires expected_files" in errors
    assert "invalid_first_rank_gate assertion first_expected_rank_lte must be an integer" in errors
    assert "invalid_literal_rank_gate assertion literal_match_rank_lte must be positive" in errors
    assert "invalid_literal_tokens_gate assertion literal_match_tokens must be a non-empty list" in errors
    assert "invalid_forbidden_gate assertion forbidden_at_5_eq must be non-negative" in errors
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
                        "text_content": "The EV6 owner notes include a direct hit.",
                        "relevance_score": 0.9,
                        "rank_score": 10.9,
                    },
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_chunk_crowding.txt",
                        "text_content": "Another EV6 chunk.",
                        "relevance_score": 0.8,
                        "rank_score": 10.8,
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
    assert output["results"][0]["metrics"]["LiteralHitFound"] is True
    assert output["results"][0]["metrics"]["LiteralHitRank"] == 1
    assert output["results"][0]["metrics"]["LiteralHitTokens"] == ["ev6"]
    assert output["results"][0]["assertions"]["passed"] is True
    assert output["results"][0]["assertions"]["skipped"] == 0
    assert output["results"][0]["top_file_details"][0]["score"] == 10.9
    assert output["results"][0]["top_files"] == [
        "corpus/vehicles/ev6_owner_notes.txt",
        "corpus/vehicles/ev6_chunk_crowding.txt",
    ]
    assert output["results"][0]["top_file_details"][0]["literal_hit"] is True
    assert output["results"][0]["top_file_details"][0]["expected"] is True


def test_cli_run_can_apply_literal_tail_suppression(search_eval, monkeypatch, tmp_path):
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
            return {"document_id": upload.document_id, "source_uri": upload.source_uri}

        def search(self, plan):
            assert plan.id == "literal_ev6_txt"
            return {
                "search_time_ms": 12.3,
                "results": [
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
                        "text_content": "The EV6 owner notes include a direct hit.",
                        "relevance_score": 0.9,
                        "rank_score": 10.9,
                    },
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_chunk_crowding.txt",
                        "text_content": "Another EV6 chunk.",
                        "relevance_score": 0.8,
                        "rank_score": 10.8,
                    },
                    {
                        "source_uri": "search_eval_v0/corpus/noise/banana_bread_recipe.txt",
                        "text_content": "Banana notes without the vehicle identifier.",
                        "relevance_score": 0.06,
                        "rank_score": 0.06,
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
        "--literal-tail-suppression",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text())
    result = output["results"][0]
    assert output["experiments"]["literal_tail_suppression"] == {
        "anchor_threshold": 10.0,
        "tail_threshold": 0.1,
        "signal": "query-class",
    }
    assert result["file_result_count"] == 2
    assert result["raw_file_result_count"] == 3
    assert result["top_files"] == [
        "corpus/vehicles/ev6_owner_notes.txt",
        "corpus/vehicles/ev6_chunk_crowding.txt",
    ]
    assert result["literal_tail_suppression"]["active"] is True
    assert result["literal_tail_suppression"]["suppressed_count"] == 1
    assert result["literal_tail_suppression"]["suppressed_preview"][0]["source_uri"] == (
        "corpus/noise/banana_bread_recipe.txt"
    )
    assert result["assertions"]["passed"] is True


def test_cli_run_can_pass_api_grouping_options(search_eval, monkeypatch, tmp_path):
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
            return {"document_id": upload.document_id, "source_uri": upload.source_uri}

        def search(self, plan):
            assert plan.id == "literal_ev6_txt"
            assert self.search_options == {
                "group_by_document": True,
                "literal_tail_suppression": "identifier-token",
                "literal_anchor_threshold": 10.0,
                "literal_tail_threshold": 0.1,
            }
            return {
                "diagnostics": {
                    "group_by_document": {"active": True},
                    "literal_tail_suppression": {"mode": "identifier-token"},
                },
                "search_time_ms": 12.3,
                "results": [
                    {
                        "source_uri": "search_eval_v0/corpus/vehicles/ev6_owner_notes.txt",
                        "text_content": "The EV6 owner notes include a direct hit.",
                        "relevance_score": 0.9,
                        "rank_score": 10.9,
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
        "--api-group-by-document",
        "--api-literal-tail-suppression", "identifier-token",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text())
    assert output["api_search_options"] == {
        "group_by_document": True,
        "literal_tail_suppression": "identifier-token",
        "literal_anchor_threshold": 10.0,
        "literal_tail_threshold": 0.1,
    }
    assert output["results"][0]["api_diagnostics"]["literal_tail_suppression"] == {
        "mode": "identifier-token"
    }


def test_cli_validate_and_plan_smoke(search_eval, capsys):
    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "validate"]) == 0
    validate_output = capsys.readouterr().out
    assert "12 documents" in validate_output
    assert "19 queries" in validate_output

    assert search_eval.main(["--fixture-root", str(FIXTURE_ROOT), "plan"]) == 0
    plan_output = capsys.readouterr().out
    assert "Query plan: 19 queries" in plan_output
    assert "literal_ev6_txt" in plan_output
