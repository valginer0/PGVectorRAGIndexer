import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEARCH_COMPARE_PATH = REPO_ROOT / "scripts" / "search_compare.py"


def load_search_compare_module():
    spec = importlib.util.spec_from_file_location("search_compare", SEARCH_COMPARE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def search(self, payload):
        self.payloads.append(payload)
        return self.responses.pop(0)


def test_dedupe_first_by_source_uri_keeps_display_order():
    search_compare = load_search_compare_module()

    deduped = search_compare.dedupe_first_by_source_uri([
        {"source_uri": "a.txt", "rank_score": 0.9, "chunk_index": 0},
        {"source_uri": "a.txt", "rank_score": 1.0, "chunk_index": 1},
        {"source_uri": "b.txt", "rank_score": 0.8, "chunk_index": 0},
    ])

    assert [result["source_uri"] for result in deduped] == ["a.txt", "b.txt"]
    assert deduped[0]["chunk_index"] == 0


def test_execute_query_pair_builds_baseline_and_document_level_payloads():
    search_compare = load_search_compare_module()
    client = FakeClient([
        (
            {
                "search_time_ms": 100,
                "results": [
                    {"source_uri": "a.txt", "rank_score": 10.0, "chunk_index": 0},
                    {"source_uri": "a.txt", "rank_score": 9.0, "chunk_index": 1},
                    {"source_uri": "b.txt", "rank_score": 0.2, "chunk_index": 0},
                ],
            },
            101.2,
        ),
        (
            {
                "search_time_ms": 50,
                "diagnostics": {"group_by_document": {"active": True}},
                "results": [
                    {"source_uri": "a.txt", "rank_score": 10.0, "chunk_index": 0},
                    {"source_uri": "c.txt", "rank_score": 0.1, "chunk_index": 0},
                ],
            },
            52.7,
        ),
    ])

    result = search_compare.execute_query_pair(
        client,
        {"id": "q001", "query": "EV6"},
        top_k=2,
        min_score=0.3,
        filters={"extensions": [".txt"]},
        literal_anchor_threshold=10.0,
        literal_tail_threshold=0.1,
        hybrid_mode="lexical-fusion-v0",
    )

    assert client.payloads[0]["top_k"] == 52
    assert client.payloads[0]["filters"] == {"extensions": [".txt"]}
    assert "group_by_document" not in client.payloads[0]
    assert "hybrid_mode" not in client.payloads[0]
    assert client.payloads[1]["top_k"] == 2
    assert client.payloads[1]["hybrid_mode"] == "lexical-fusion-v0"
    assert client.payloads[1]["group_by_document"] is True
    assert client.payloads[1]["literal_tail_suppression"] == "identifier-token"
    assert result["baseline"]["top_files"] == ["a.txt", "b.txt"]
    assert result["document_level"]["confirmed"] is True
    assert result["document_level"]["top_files"] == ["a.txt", "c.txt"]
    assert result["comparison"]["added_by_document_level"] == ["c.txt"]
    assert result["comparison"]["removed_by_document_level"] == ["b.txt"]


def test_main_writes_read_only_comparison_json(monkeypatch, tmp_path):
    search_compare = load_search_compare_module()
    output_path = tmp_path / "compare.json"

    class FakeHTTPClient:
        def __init__(self, base_url, api_key=None, timeout=120.0):
            self.base_url = base_url

        def health(self):
            return {"status": "healthy"}

        def search(self, payload):
            if payload.get("group_by_document"):
                return (
                    {
                        "diagnostics": {"group_by_document": {"active": True}},
                        "results": [{"source_uri": "grouped.txt", "rank_score": 10.0}],
                    },
                    10.0,
                )
            return (
                {
                    "results": [{"source_uri": "baseline.txt", "rank_score": 1.0}],
                },
                20.0,
            )

    monkeypatch.setattr(search_compare, "SearchCompareHTTPClient", FakeHTTPClient)

    status = search_compare.main([
        "--api-base", "http://example.test",
        "--query", "EV6",
        "--top-k", "1",
        "--hybrid-mode", "lexical-fusion-v0",
        "--output-json", str(output_path),
    ])

    assert status == 0
    output = json.loads(output_path.read_text())
    assert output["query_count"] == 1
    assert output["document_level_options"]["hybrid_mode"] == "lexical-fusion-v0"
    assert output["results"][0]["baseline"]["top_files"] == ["baseline.txt"]
    assert output["results"][0]["document_level"]["top_files"] == ["grouped.txt"]


def test_main_rejects_negative_threshold_before_http_client(monkeypatch, capsys):
    search_compare = load_search_compare_module()

    def fail_if_instantiated(*_args, **_kwargs):
        raise AssertionError("HTTP client should not be created for invalid thresholds")

    monkeypatch.setattr(search_compare, "SearchCompareHTTPClient", fail_if_instantiated)

    status = search_compare.main([
        "--query", "EV6",
        "--literal-anchor-threshold", "-1",
    ])

    assert status == 1
    assert "--literal-anchor-threshold must be non-negative" in capsys.readouterr().err
