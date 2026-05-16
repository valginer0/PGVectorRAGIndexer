"""
In-process rate limiting middleware for the FastAPI API.

This is intentionally lightweight: it protects single-process desktop and
small-server deployments without adding an external service dependency. Larger
multi-worker deployments should still add reverse-proxy or shared-store limits.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


RATE_LIMIT_HEADER = "X-RateLimit-Limit"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
TRUSTED_OPERATION_HEADER = "X-PGVectorRAGIndexer-Operation"
TRUSTED_BULK_INDEXING_OPERATION = "bulk-indexing"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int


class FixedWindowRateLimiter:
    """Thread-safe fixed-window limiter keyed by API key hash or client IP."""

    def __init__(
        self,
        limit_per_minute: int,
        *,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.time,
    ):
        self.limit = max(0, int(limit_per_minute))
        self.window_seconds = max(1, int(window_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._counts: Dict[Tuple[str, int], int] = {}

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        window = int(now // self.window_seconds)
        reset_at = int((window + 1) * self.window_seconds)

        if self.limit <= 0:
            return RateLimitDecision(True, 0, 0, reset_at)

        with self._lock:
            self._purge_old_windows(window)
            bucket = (key, window)
            current = self._counts.get(bucket, 0)

            if current >= self.limit:
                return RateLimitDecision(False, self.limit, 0, reset_at)

            current += 1
            self._counts[bucket] = current
            remaining = max(0, self.limit - current)
            return RateLimitDecision(True, self.limit, remaining, reset_at)

    def _purge_old_windows(self, current_window: int) -> None:
        stale = [bucket for bucket in self._counts if bucket[1] < current_window]
        for bucket in stale:
            del self._counts[bucket]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-minute API rate limiting with standard response headers."""

    def __init__(
        self,
        app,
        *,
        limit_per_minute: int,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self._limiter = FixedWindowRateLimiter(
            limit_per_minute,
            window_seconds=window_seconds,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method.upper() == "OPTIONS"
            or self._limiter.limit <= 0
            or _is_trusted_bulk_indexing_request(request)
        ):
            return await call_next(request)

        decision = self._limiter.check(_rate_limit_key(request))
        headers = _rate_limit_headers(decision)

        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "Rate limit exceeded. Try again after the reset time.",
                    "details": {
                        "limit_per_minute": decision.limit,
                        "reset_at": decision.reset_at,
                    },
                },
                headers=headers,
            )

        response: Response = await call_next(request)
        for name, value in headers.items():
            response.headers[name] = value
        return response


def _rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("x-api-key")
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"api-key:{digest}"

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def _is_trusted_bulk_indexing_request(request: Request) -> bool:
    """Skip throttling for first-party bulk indexing/probe calls."""
    if request.headers.get(TRUSTED_OPERATION_HEADER) != TRUSTED_BULK_INDEXING_OPERATION:
        return False

    method = request.method.upper()
    path = request.url.path.rstrip("/")

    if method == "POST" and path in {
        "/index",
        "/api/v1/index",
        "/upload-and-index",
        "/api/v1/upload-and-index",
    }:
        return True

    if method == "GET":
        return path.startswith("/documents/") or path.startswith("/api/v1/documents/")

    return False


def _rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        RATE_LIMIT_HEADER: str(decision.limit),
        RATE_LIMIT_REMAINING_HEADER: str(decision.remaining),
        RATE_LIMIT_RESET_HEADER: str(decision.reset_at),
    }
