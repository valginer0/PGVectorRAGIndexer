from fastapi import FastAPI
from fastapi.testclient import TestClient

from rate_limit import RateLimitMiddleware


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


def test_rate_limit_can_be_disabled():
    client = _make_client(limit=0)

    for _ in range(5):
        response = client.get("/ping")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers
