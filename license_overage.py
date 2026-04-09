"""
Shame middleware for license seat-count enforcement.

Adds warning headers to every API response when the active user count exceeds
the licensed seat count.  No functional lock — queries and uploads continue
to work.  Community edition is always a no-op.

Headers injected when overage > 0:
  X-License-Overage: true
  X-License-Overage-Count: <n>
  Warning: 299 RAGVault "Seat count exceeded: N active users on M-seat license"

The middleware caches the overage state for ``OVERAGE_CACHE_TTL_SECONDS``
(default 300 s) to avoid per-request DB queries.
"""

import logging
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

OVERAGE_CACHE_TTL_SECONDS = 300  # 5 minutes


class _OverageCache:
    """Thread-safe (GIL-protected) in-memory cache for the overage state."""

    def __init__(self):
        self._overage: int = 0
        self._licensed: int = 0
        self._active: int = 0
        self._last_refresh: float = 0.0

    def is_stale(self) -> bool:
        return (time.monotonic() - self._last_refresh) >= OVERAGE_CACHE_TTL_SECONDS

    def refresh(self) -> None:
        """Re-compute overage from the live DB. Never raises."""
        try:
            from license import get_current_license
            from users import count_active_users

            lic = get_current_license()
            if not lic.is_team:
                self._overage = 0
                self._licensed = 0
                self._active = 0
                self._last_refresh = time.monotonic()
                return

            licensed = lic.seats
            active = count_active_users()
            self._licensed = licensed
            self._active = active
            self._overage = max(0, active - licensed)
            self._last_refresh = time.monotonic()
        except Exception as e:
            logger.debug("Overage cache refresh failed: %s", e)
            self._last_refresh = time.monotonic()  # back-off — don't retry every request

    @property
    def overage(self) -> int:
        return self._overage

    @property
    def licensed(self) -> int:
        return self._licensed

    @property
    def active(self) -> int:
        return self._active


_cache = _OverageCache()


def invalidate_overage_cache() -> None:
    """Force the next request to recompute the overage state.

    Call this after installing/removing a license key or changing user counts.
    """
    # Set far enough in the past to guarantee is_stale() returns True
    # regardless of system uptime (time.monotonic() could be < TTL on
    # freshly booted machines).
    _cache._last_refresh = time.monotonic() - OVERAGE_CACHE_TTL_SECONDS - 1


class LicenseOverageMiddleware(BaseHTTPMiddleware):
    """Injects X-License-Overage headers when seat count is exceeded."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # Refresh cache lazily on the first stale request
        if _cache.is_stale():
            _cache.refresh()

        if _cache.overage > 0:
            n = _cache.overage
            total = _cache.active
            seats = _cache.licensed
            response.headers["X-License-Overage"] = "true"
            response.headers["X-License-Overage-Count"] = str(n)
            response.headers["Warning"] = (
                f'299 RAGVault "Seat count exceeded: {total} active users on '
                f'{seats}-seat license. Purchase additional licenses at ragvault.net/pricing."'
            )

        return response
