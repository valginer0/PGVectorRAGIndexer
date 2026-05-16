from fastapi import FastAPI
from fastapi.testclient import TestClient

from rate_limit import (
    RateLimitMiddleware,
    TRUSTED_BULK_INDEXING_OPERATION,
    TRUSTED_OPERATION_HEADER,
)


def _make_client(limit: int) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=limit)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


def test_rate_limit_returns_429_after_limit():
    client = _make_client(limit=2)

    assert client.get("/ping").status_code == 200
    second = client.get("/ping")
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Limit"] == "2"
    assert second.headers["X-RateLimit-Remaining"] == "0"

    limited = client.get("/ping")

    assert limited.status_code == 429
    assert limited.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert limited.headers["X-RateLimit-Limit"] == "2"
    assert limited.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in limited.headers
    assert "Retry-After" in limited.headers


def test_rate_limit_can_be_disabled():
    client = _make_client(limit=0)

    for _ in range(5):
        response = client.get("/ping")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_trusted_bulk_indexing_upload_bypasses_rate_limit():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=1)

    @app.post("/api/v1/upload-and-index")
    async def upload_and_index():
        return {"ok": True}

    client = TestClient(app)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    for _ in range(3):
        response = client.post("/api/v1/upload-and-index", headers=headers)
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_trusted_bulk_indexing_metadata_probe_bypasses_rate_limit():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=1)

    @app.get("/api/v1/documents/{document_id}")
    async def get_document(document_id: str):
        return {"id": document_id}

    client = TestClient(app)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    for _ in range(3):
        response = client.get("/api/v1/documents/source-id", headers=headers)
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_trusted_bulk_indexing_scan_bypasses_rate_limit():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=1)

    @app.post("/api/v1/watched-folders/{folder_id}/scan")
    async def scan_folder(folder_id: str):
        return {"id": folder_id}

    client = TestClient(app)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    for _ in range(3):
        response = client.post("/api/v1/watched-folders/f1/scan", headers=headers)
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_trusted_bulk_indexing_lock_bypasses_rate_limit():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=1)

    @app.post("/api/v1/documents/locks/acquire")
    async def acquire_lock():
        return {"ok": True}

    client = TestClient(app)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    for _ in range(3):
        response = client.post("/api/v1/documents/locks/acquire", headers=headers)
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_trusted_bulk_header_does_not_bypass_document_collection_reads():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit_per_minute=1)

    @app.get("/api/v1/documents/tree")
    async def document_tree():
        return {"items": []}

    client = TestClient(app)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    assert client.get("/api/v1/documents/tree", headers=headers).status_code == 200
    assert client.get("/api/v1/documents/tree", headers=headers).status_code == 429


def test_trusted_bulk_header_does_not_bypass_unrelated_endpoints():
    client = _make_client(limit=1)
    headers = {TRUSTED_OPERATION_HEADER: TRUSTED_BULK_INDEXING_OPERATION}

    assert client.get("/ping", headers=headers).status_code == 200
    assert client.get("/ping", headers=headers).status_code == 429
