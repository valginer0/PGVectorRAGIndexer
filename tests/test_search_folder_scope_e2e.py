"""End-to-end smoke for folder-scoped search over the REST API.

Uploads real documents into a folder structure, then verifies scoped
searches and folder-delete previews through the HTTP surface (routes →
filters → SQL), not just the unit level. Uses min_score=0.0 because short
test documents can score below the default similarity threshold.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api import app


@pytest.fixture(scope="module")
def run_id():
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def corpus(client, run_id):
    """Upload documents under a unique folder structure for this run.

    Teardown deletes everything under the run's unique root so later tests
    that assert exact document counts are not polluted (the per-test
    db_manager TRUNCATE does not apply to this module-scoped fixture).
    """
    root = f"scope_e2e_{run_id}"
    docs = {
        f"{root}/ProjectA/contracts/supply.txt":
            "Supply agreement with Acme for industrial widgets.",
        f"{root}/ProjectA/archive/old_supply.txt":
            "Archived supply agreement draft for industrial widgets.",
        f"{root}/ProjectB/notes.txt":
            "Meeting notes about industrial widgets roadmap.",
        f"{root}/report_2024/summary.txt":
            "Annual widget report for the year.",
        f"{root}/reportX2024/summary.txt":
            "Unrelated widget report in a similarly named sibling folder.",
    }
    for uri, text in docs.items():
        resp = client.post(
            "/upload-and-index",
            files={"file": (uri.rsplit("/", 1)[-1], text.encode(), "text/plain")},
            data={"custom_source_uri": uri, "force_reindex": "true"},
        )
        assert resp.status_code == 200, resp.text

    yield root

    resp = client.post("/documents/bulk-delete", json={
        "filters": {"source_uri_prefix": root},
        "preview": False,
    })
    assert resp.status_code == 200, resp.text


def _search(client, corpus_root, use_hybrid, **filter_overrides):
    filters = {k: [f"{corpus_root}/{p}" for p in v]
               for k, v in filter_overrides.items()}
    resp = client.post("/search", json={
        "query": "industrial widgets agreement",
        "top_k": 20,
        "min_score": 0.0,
        "use_hybrid": use_hybrid,
        "source": "postgres",
        "filters": filters,
    })
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    return {r["source_uri"] for r in results}


class TestScopedSearchE2E:
    @pytest.mark.parametrize("use_hybrid", [False, True],
                             ids=["non-hybrid", "hybrid"])
    def test_include_scopes_to_folder(self, client, corpus, use_hybrid):
        uris = _search(client, corpus, use_hybrid,
                       path_prefixes=["ProjectA"])
        assert uris, "scoped search returned nothing"
        assert all(f"{corpus}/ProjectA/" in u for u in uris)

    @pytest.mark.parametrize("use_hybrid", [False, True],
                             ids=["non-hybrid", "hybrid"])
    def test_exclude_wins_inside_include(self, client, corpus, use_hybrid):
        uris = _search(client, corpus, use_hybrid,
                       path_prefixes=["ProjectA"],
                       excluded_path_prefixes=["ProjectA/archive"])
        assert any("contracts" in u for u in uris)
        assert not any("archive" in u for u in uris)

    @pytest.mark.parametrize("use_hybrid", [False, True],
                             ids=["non-hybrid", "hybrid"])
    def test_underscore_folder_matches_literally(self, client, corpus, use_hybrid):
        # 'report_2024' must never match sibling 'reportX2024' via the
        # LIKE '_' wildcard.
        uris = _search(client, corpus, use_hybrid,
                       path_prefixes=["report_2024"])
        assert any(f"{corpus}/report_2024/" in u for u in uris)
        assert not any("reportX2024" in u for u in uris)

    def test_health_advertises_search_backend(self, client):
        backend = client.get("/health").json().get("search_backend")
        assert backend in ("lancedb", "postgres")


class TestPostgresFallbackWhenLanceDBDisabled:
    """RETRIEVAL_LANCEDB_ENABLED=false: /health must advertise postgres and a
    default (source omitted) scoped search must fall back to Postgres and
    still scope correctly."""

    def test_health_signal_and_scoped_search_fall_back(self, client, corpus):
        from config import get_config
        cfg = get_config()
        original = cfg.retrieval.lancedb_enabled
        cfg.retrieval.lancedb_enabled = False
        try:
            assert client.get("/health").json()["search_backend"] == "postgres"

            resp = client.post("/search", json={
                "query": "industrial widgets agreement",
                "top_k": 20,
                "min_score": 0.0,
                "use_hybrid": True,
                # no "source": the backend decides — disabled LanceDB must
                # fall back to Postgres, not error.
                "filters": {"path_prefixes": [f"{corpus}/ProjectA"]},
            })
            assert resp.status_code == 200, resp.text
            uris = {r["source_uri"] for r in resp.json()["results"]}
            assert uris, "fallback scoped search returned nothing"
            assert all(f"{corpus}/ProjectA/" in u for u in uris)
        finally:
            cfg.retrieval.lancedb_enabled = original

    def test_health_signal_restored_when_enabled(self, client):
        from config import get_config
        cfg = get_config()
        original = cfg.retrieval.lancedb_enabled
        cfg.retrieval.lancedb_enabled = True
        try:
            assert client.get("/health").json()["search_backend"] == "lancedb"
        finally:
            cfg.retrieval.lancedb_enabled = original


class TestFolderDeletePreviewE2E:
    def test_preview_counts_literal_folder_only(self, client, corpus):
        resp = client.post("/documents/bulk-delete", json={
            "filters": {"source_uri_prefix": f"{corpus}/report_2024"},
            "preview": True,
        })
        assert resp.status_code == 200, resp.text
        # Exactly the one doc under report_2024 — the reportX2024 sibling
        # must not be counted.
        assert resp.json()["document_count"] == 1
