"""
/search route behavior fixes (ultrareview local pass, 2026-06-12).

- The readiness gate (_should_use_lancedb) must run exactly once per request,
  so a concurrent mutation can't turn a completed search into a 503.
- The empty-index count/message is computed only when the search returned no
  results, so the success path doesn't scan document_chunks.
- A hybrid request served by the LanceDB engine is surfaced via a diagnostic
  instead of being silently ignored.
"""

from types import SimpleNamespace

import pytest


def _result(**over):
    base = dict(
        chunk_id=1, document_id="d1", chunk_index=0, text_content="hello",
        source_uri="/a.txt", distance=0.1, relevance_score=0.9, rank_score=None,
        metadata={}, document_type=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _FakeRetriever:
    def __init__(self, results, using_lancedb=True):
        self._results = results
        self._using_lancedb = using_lancedb
        self.readiness_calls = 0

    def _should_use_lancedb(self, source="lancedb"):
        self.readiness_calls += 1
        return self._using_lancedb

    def search_lancedb_parent_child(self, **kw):
        return list(self._results), {"engine": "lancedb_parent_child"}

    def search(self, **kw):
        return list(self._results)

    def search_hybrid(self, **kw):
        return list(self._results)


def _patch_common(monkeypatch, retriever):
    from routers import search_api
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)
    monkeypatch.setattr(
        "config.get_config",
        lambda: SimpleNamespace(retrieval=SimpleNamespace(lancedb_enabled=True)),
    )
    return search_api


async def test_readiness_gate_called_once_on_success(monkeypatch):
    ret = _FakeRetriever([_result()], using_lancedb=True)
    search_api = _patch_common(monkeypatch, ret)
    from api_models import SearchRequest

    await search_api.search_documents(SearchRequest(query="q"), key_record=None)
    assert ret.readiness_calls == 1


async def test_nonempty_results_skip_empty_index_scan(monkeypatch):
    ret = _FakeRetriever([_result()], using_lancedb=True)
    search_api = _patch_common(monkeypatch, ret)
    from api_models import SearchRequest

    # If the count path runs, this would blow up the request.
    def _boom():
        raise AssertionError("empty-index scan ran on a non-empty result set")

    monkeypatch.setattr("services.get_lancedb_adapter", _boom)

    resp = await search_api.search_documents(SearchRequest(query="q"), key_record=None)
    assert resp.total_results == 1
    assert resp.message is None


async def test_empty_results_report_empty_index(monkeypatch):
    ret = _FakeRetriever([], using_lancedb=True)
    search_api = _patch_common(monkeypatch, ret)
    from api_models import SearchRequest

    fake_adapter = SimpleNamespace(get_statistics=lambda: {"total_documents": 0})
    monkeypatch.setattr("services.get_lancedb_adapter", lambda: fake_adapter)

    resp = await search_api.search_documents(SearchRequest(query="q"), key_record=None)
    assert resp.total_results == 0
    assert resp.message and "empty" in resp.message.lower()


async def test_hybrid_request_served_by_lancedb_is_surfaced(monkeypatch):
    ret = _FakeRetriever([_result()], using_lancedb=True)
    search_api = _patch_common(monkeypatch, ret)
    from api_models import SearchRequest

    resp = await search_api.search_documents(
        SearchRequest(query="q", use_hybrid=True, hybrid_mode="rerank-v0"),
        key_record=None,
    )
    assert resp.diagnostics is not None
    override = resp.diagnostics.get("engine_override")
    assert override is not None
    assert override["requested"] == "rerank-v0"
    assert override["served_by"] == "lancedb_parent_child"


async def test_no_override_diagnostic_when_not_hybrid(monkeypatch):
    ret = _FakeRetriever([_result()], using_lancedb=True)
    search_api = _patch_common(monkeypatch, ret)
    from api_models import SearchRequest

    resp = await search_api.search_documents(SearchRequest(query="q"), key_record=None)
    if resp.diagnostics:
        assert "engine_override" not in resp.diagnostics
