"""
Tests for the REST-backed MCP Server (mcp_server.py).

These tests verify the tool implementation functions without needing the MCP
library or a running backend.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class FakeMCPAPIClient:
    def __init__(self):
        self.calls = []
        self.search_response = {
            "query": "test query",
            "total_results": 2,
            "search_time_ms": 12.5,
            "diagnostics": {"engine": "lancedb_parent_child"},
            "results": [
                {
                    "chunk_id": 101,
                    "document_id": "doc1",
                    "chunk_index": 0,
                    "source_uri": "/docs/test.txt",
                    "text_content": "This is test content",
                    "rank_score": 0.95,
                    "relevance_score": 0.91,
                    "distance": 0.09,
                    "document_type": "note",
                    "metadata": {"visibility": "shared"},
                },
                {
                    "chunk_id": 102,
                    "document_id": "doc2",
                    "chunk_index": 1,
                    "source_uri": "/docs/other.md",
                    "text_content": "Another result",
                    "relevance_score": 0.85,
                    "distance": 0.15,
                    "metadata": {},
                },
            ],
        }
        self.index_response = {
            "status": "success",
            "document_id": "abc123",
            "source_uri": "/docs/test.pdf",
            "chunks_indexed": 10,
            "message": "indexed",
            "indexed_at": "2026-06-16T12:00:00Z",
        }
        self.list_response = {
            "items": [
                {
                    "document_id": "doc1",
                    "source_uri": "/docs/test.txt",
                    "document_type": "note",
                    "chunk_count": 5,
                    "indexed_at": "2026-06-16T12:00:00Z",
                    "visibility": "private",
                    "owner_id": "user-1",
                }
            ],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return self.search_response

    def upload_and_index(self, **kwargs):
        self.calls.append(("upload_and_index", kwargs))
        return self.index_response

    def list_documents(self, **kwargs):
        self.calls.append(("list_documents", kwargs))
        return self.list_response


def test_load_config_uses_rest_env(monkeypatch):
    from mcp_server import load_config

    monkeypatch.setenv("PGVECTOR_MCP_BASE_URL", "https://example.test")
    monkeypatch.setenv("PGVECTOR_MCP_API_KEY", "pgv_sk_test")
    monkeypatch.setenv("PGVECTOR_MCP_TIMEOUT", "42")

    cfg = load_config()

    assert cfg.api_base == "https://example.test/api/v1"
    assert cfg.api_key == "pgv_sk_test"
    assert cfg.timeout == 42


def test_load_config_accepts_api_base(monkeypatch):
    from mcp_server import load_config

    monkeypatch.setenv("PGVECTOR_MCP_BASE_URL", "https://example.test/api/v1")

    assert load_config().api_base == "https://example.test/api/v1"


def test_search_returns_structured_results():
    from mcp_server import search_documents_impl

    fake = FakeMCPAPIClient()
    with patch("mcp_server._get_api_client", return_value=fake):
        result = search_documents_impl("test query", top_k=5, use_hybrid=True, source="postgres")

    assert result["ok"] is True
    assert result["query"] == "test query"
    assert result["total_results"] == 2
    assert result["diagnostics"] == {"engine": "lancedb_parent_child"}
    assert result["results"][0] == {
        "rank": 1,
        "document_id": "doc1",
        "chunk_id": 101,
        "chunk_index": 0,
        "source_uri": "/docs/test.txt",
        "document_type": "note",
        "score": 0.95,
        "rank_score": 0.95,
        "relevance_score": 0.91,
        "distance": 0.09,
        "metadata": {"visibility": "shared"},
        "text": "This is test content",
    }
    assert fake.calls == [
        (
            "search",
            {
                "query": "test query",
                "top_k": 5,
                "use_hybrid": True,
                "source": "postgres",
            },
        )
    ]


def test_search_error_returns_structured_failure():
    from mcp_server import search_documents_impl

    fake = FakeMCPAPIClient()
    fake.search = MagicMock(side_effect=RuntimeError("backend down"))

    with patch("mcp_server._get_api_client", return_value=fake):
        result = search_documents_impl("test")

    assert result == {
        "ok": False,
        "operation": "search",
        "error": "backend down",
    }


def test_index_uploads_local_file(tmp_path: Path):
    from mcp_server import index_document_impl

    file_path = tmp_path / "doc.md"
    file_path.write_text("# Test\n", encoding="utf-8")
    fake = FakeMCPAPIClient()

    with patch("mcp_server._get_api_client", return_value=fake):
        result = index_document_impl(str(file_path), force=True, document_type="note")

    assert result["ok"] is True
    assert result["document_id"] == "abc123"
    assert result["chunks_indexed"] == 10
    assert fake.calls == [
        (
            "upload_and_index",
            {"path": file_path, "force": True, "document_type": "note"},
        )
    ]


def test_index_missing_file_does_not_call_api(tmp_path: Path):
    from mcp_server import index_document_impl

    fake = FakeMCPAPIClient()

    with patch("mcp_server._get_api_client", return_value=fake):
        result = index_document_impl(str(tmp_path / "missing.pdf"))

    assert result["ok"] is False
    assert "File not found" in result["error"]
    assert fake.calls == []


def test_list_documents_returns_visibility_fields():
    from mcp_server import list_documents_impl

    fake = FakeMCPAPIClient()
    with patch("mcp_server._get_api_client", return_value=fake):
        result = list_documents_impl(limit=20)

    assert result == {
        "ok": True,
        "total": 1,
        "limit": 20,
        "offset": 0,
        "documents": [
            {
                "document_id": "doc1",
                "source_uri": "/docs/test.txt",
                "document_type": "note",
                "chunk_count": 5,
                "indexed_at": "2026-06-16T12:00:00Z",
                "last_updated": None,
                "visibility": "private",
                "owner_id": "user-1",
                "metadata": {},
            }
        ],
    }
    assert fake.calls == [("list_documents", {"limit": 20})]


def test_api_client_sends_auth_header_and_search_payload():
    from mcp_server import MCPAPIClient, MCPConfig

    cfg = MCPConfig(api_base="https://example.test/api/v1", api_key="pgv_sk_test", timeout=99)
    client = MCPAPIClient(cfg)
    response = MagicMock(status_code=200)
    response.json.return_value = {"results": []}
    client.session.request = MagicMock(return_value=response)

    assert client.search(query="abc", top_k=3, use_hybrid=False, source="lancedb") == {"results": []}
    assert client.session.headers["X-API-Key"] == "pgv_sk_test"
    client.session.request.assert_called_once_with(
        "POST",
        "https://example.test/api/v1/search",
        json={"query": "abc", "top_k": 3, "use_hybrid": False, "source": "lancedb"},
        timeout=99,
    )


def test_api_client_maps_http_errors():
    from mcp_server import MCPAPIClient, MCPAPIError, MCPConfig

    client = MCPAPIClient(MCPConfig(api_base="http://localhost:8000/api/v1"))
    response = MagicMock(status_code=403, text="")
    response.json.return_value = {"detail": "not allowed"}
    client.session.request = MagicMock(return_value=response)

    with pytest.raises(MCPAPIError, match="not allowed") as err:
        client.list_documents(limit=5)

    assert err.value.status_code == 403
