import pytest

from desktop_app.utils.api_client import APIClient


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def api_client():
    return APIClient(base_url="http://localhost")


def test_list_documents_accepts_plain_list(monkeypatch, api_client):
    items = [
        {
            "document_id": "doc-1",
            "source_uri": "C:/tmp/doc1.txt",
            "chunk_count": 3,
            "indexed_at": "2025-10-01T12:00:00Z",
        }
    ]

    def fake_get(url, params, timeout):
        assert url.endswith("/documents")
        return DummyResponse(items)

    monkeypatch.setattr("desktop_app.utils.api_client.requests.get", fake_get)

    result = api_client.list_documents(limit=25, offset=5, sort_by="indexed_at", sort_dir="desc")

    assert result["items"] == items
    assert result["total"] == len(items)
    assert result["limit"] == 25
    assert result["offset"] == 5
    assert result["sort"] == {"by": "indexed_at", "direction": "desc"}


def test_list_documents_accepts_legacy_documents_key(monkeypatch, api_client):
    legacy_payload = {
        "documents": [
            {
                "document_id": "legacy-1",
                "source_uri": "C:/tmp/legacy1.txt",
                "chunk_count": 1,
                "indexed_at": "2025-10-02T09:00:00Z",
            }
        ],
        "total": 1,
        "limit": 10,
        "offset": 0,
    }

    def fake_get(url, params, timeout):
        return DummyResponse(legacy_payload)

    monkeypatch.setattr("desktop_app.utils.api_client.requests.get", fake_get)

    result = api_client.list_documents(limit=10, offset=0, sort_by="indexed_at", sort_dir="desc")

    assert result["items"] == legacy_payload["documents"]
    assert result["total"] == 1
    assert result["limit"] == 10
    assert result["offset"] == 0
    assert result["sort"] == {"by": "indexed_at", "direction": "desc"}


def test_list_documents_passthrough_for_paginated_payload(monkeypatch, api_client):
    paginated_payload = {
        "items": [
            {
                "document_id": "doc-2",
                "source_uri": "C:/tmp/doc2.txt",
                "chunk_count": 2,
                "indexed_at": "2025-10-03T10:00:00Z",
                "metadata": {"type": "report"},
            }
        ],
        "total": 1,
        "limit": 25,
        "offset": 0,
        "sort": {"by": "indexed_at", "direction": "desc"},
    }

    def fake_get(url, params, timeout):
        return DummyResponse(paginated_payload)

    monkeypatch.setattr("desktop_app.utils.api_client.requests.get", fake_get)

    result = api_client.list_documents(limit=25, offset=0, sort_by="indexed_at", sort_dir="desc")

    assert result == paginated_payload
