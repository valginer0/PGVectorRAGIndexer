from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api_models import SearchRequest
from routers import search_api


def _result(source_uri, *, rank_score, text_content="", chunk_index=0, chunk_id=1):
    return SimpleNamespace(
        chunk_id=chunk_id,
        document_id=f"doc-{source_uri}",
        chunk_index=chunk_index,
        text_content=text_content,
        source_uri=source_uri,
        distance=1.0 - min(rank_score, 1.0),
        relevance_score=min(rank_score, 1.0),
        rank_score=rank_score,
        metadata={},
        document_type=None,
    )


class _FakeRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search_hybrid(self, **kwargs):
        self.calls.append(("hybrid", kwargs))
        return self.results

    def search_hybrid_fusion_v0(self, **kwargs):
        self.calls.append(("fusion", kwargs))
        return self.results, {"hybrid_fusion_v0": {"active": True}}

    def search_hybrid_rerank_v0(self, **kwargs):
        self.calls.append(("rerank", kwargs))
        return self.results, {"rerank_v0": {"active": True}}

    def search(self, **kwargs):
        self.calls.append(("vector", kwargs))
        return self.results


def test_identifier_query_tokens_skip_single_letter_words():
    assert search_api._identifier_query_tokens("I have a JWT question about EV6") == ["jwt", "ev6"]


@pytest.mark.asyncio
async def test_search_default_keeps_chunk_results(monkeypatch):
    retriever = _FakeRetriever([
        _result("a.txt", rank_score=0.9, chunk_id=1),
        _result("a.txt", rank_score=0.8, chunk_id=2),
        _result("b.txt", rank_score=0.7, chunk_id=3),
    ])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6",
        top_k=2,
        use_hybrid=True,
    ))

    assert [result.source_uri for result in response.results] == ["a.txt", "a.txt", "b.txt"]
    assert response.total_results == 3
    assert response.diagnostics is None
    assert retriever.calls[0][1]["top_k"] == 2


@pytest.mark.asyncio
async def test_search_group_by_document_keeps_best_chunk_per_source(monkeypatch):
    retriever = _FakeRetriever([
        _result("a.txt", rank_score=0.5, chunk_index=0, chunk_id=1),
        _result("a.txt", rank_score=0.9, chunk_index=1, chunk_id=2),
        _result("b.txt", rank_score=0.7, chunk_id=3),
        _result("c.txt", rank_score=0.6, chunk_id=4),
    ])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6",
        top_k=2,
        use_hybrid=True,
        group_by_document=True,
    ))

    assert [result.source_uri for result in response.results] == ["a.txt", "b.txt"]
    assert response.results[0].chunk_index == 1
    assert response.total_results == 2
    assert retriever.calls[0][1]["top_k"] == 40
    assert response.diagnostics["group_by_document"] == {
        "active": True,
        "raw_result_count": 4,
        "grouped_result_count": 3,
        "requested_top_k": 2,
        "backend_top_k": 40,
    }


@pytest.mark.asyncio
async def test_search_identifier_tail_suppression_filters_low_score_non_literal_files(monkeypatch):
    retriever = _FakeRetriever([
        _result("ev6.txt", rank_score=10.9, text_content="EV6 owner notes", chunk_id=1),
        _result("banana.txt", rank_score=0.05, text_content="Banana recipe", chunk_id=2),
        _result("charging.txt", rank_score=0.2, text_content="Charging overview", chunk_id=3),
    ])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6",
        top_k=5,
        use_hybrid=True,
        group_by_document=True,
        literal_tail_suppression="identifier-token",
        literal_anchor_threshold=None,
        literal_tail_threshold=None,
    ))

    assert [result.source_uri for result in response.results] == ["ev6.txt", "charging.txt"]
    diagnostics = response.diagnostics["literal_tail_suppression"]
    assert diagnostics["active"] is True
    assert diagnostics["identifier_tokens"] == ["ev6"]
    assert diagnostics["suppressed_count"] == 1
    assert diagnostics["suppressed_preview"][0]["source_uri"] == "banana.txt"
    assert response.diagnostics["group_by_document"]["suppressed_grouped_result_count"] == 2


@pytest.mark.asyncio
async def test_literal_tail_suppression_requires_document_grouping(monkeypatch):
    retriever = _FakeRetriever([])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    with pytest.raises(HTTPException) as exc_info:
        await search_api.search_documents(SearchRequest(
            query="EV6",
            use_hybrid=True,
            literal_tail_suppression="identifier-token",
        ))

    assert exc_info.value.status_code == 400
    assert "group_by_document=true" in exc_info.value.detail


@pytest.mark.asyncio
async def test_hybrid_mode_requires_hybrid_search(monkeypatch):
    retriever = _FakeRetriever([])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    with pytest.raises(HTTPException) as exc_info:
        await search_api.search_documents(SearchRequest(
            query="EV6",
            use_hybrid=False,
            hybrid_mode="lexical-fusion-v0",
        ))

    assert exc_info.value.status_code == 400
    assert "hybrid_mode requires use_hybrid=true" in exc_info.value.detail


@pytest.mark.asyncio
async def test_hybrid_mode_rejects_unknown_value(monkeypatch):
    retriever = _FakeRetriever([])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    with pytest.raises(HTTPException) as exc_info:
        await search_api.search_documents(SearchRequest(
            query="EV6",
            use_hybrid=True,
            hybrid_mode="mystery",
        ))

    assert exc_info.value.status_code == 400
    assert "legacy, lexical-fusion-v0, or rerank-v0" in exc_info.value.detail


@pytest.mark.asyncio
async def test_hybrid_mode_legacy_uses_existing_hybrid_path(monkeypatch):
    retriever = _FakeRetriever([_result("ev6.txt", rank_score=10.0)])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6",
        top_k=1,
        use_hybrid=True,
        hybrid_mode="legacy",
    ))

    assert [result.source_uri for result in response.results] == ["ev6.txt"]
    assert retriever.calls[0][0] == "hybrid"
    assert response.diagnostics is None


@pytest.mark.asyncio
async def test_hybrid_mode_lexical_fusion_uses_fusion_path(monkeypatch):
    retriever = _FakeRetriever([_result("ev6.txt", rank_score=0.03)])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6 charging",
        top_k=1,
        use_hybrid=True,
        hybrid_mode="lexical-fusion-v0",
    ))

    assert [result.source_uri for result in response.results] == ["ev6.txt"]
    assert retriever.calls[0][0] == "fusion"
    assert retriever.calls[0][1]["top_k"] == 1
    assert response.diagnostics == {"hybrid_fusion_v0": {"active": True}}


@pytest.mark.asyncio
async def test_hybrid_mode_rerank_uses_rerank_path(monkeypatch):
    retriever = _FakeRetriever([_result("ev6.txt", rank_score=0.95)])
    monkeypatch.setattr(search_api, "get_retriever", lambda: retriever)

    response = await search_api.search_documents(SearchRequest(
        query="EV6 charging",
        top_k=1,
        use_hybrid=True,
        hybrid_mode="rerank-v0",
    ))

    assert [result.source_uri for result in response.results] == ["ev6.txt"]
    assert retriever.calls[0][0] == "rerank"
    assert retriever.calls[0][1]["top_k"] == 1
    assert response.diagnostics == {"rerank_v0": {"active": True}}
