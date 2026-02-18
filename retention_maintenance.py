"""Independent retention maintenance loop.

Runs periodic retention jobs regardless of whether the server scheduler
is enabled, so cleanup does not depend on #6b runtime flags.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

RETENTION_MAINTENANCE_ENABLED_ENV = "RETENTION_MAINTENANCE_ENABLED"
RETENTION_MAINTENANCE_INTERVAL_SECONDS_ENV = "RETENTION_MAINTENANCE_INTERVAL_SECONDS"
DEFAULT_RETENTION_MAINTENANCE_INTERVAL_SECONDS = 24 * 3600


class RetentionMaintenanceRunner:
    """Background loop that periodically applies retention policy."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run_at: Optional[str] = None

    @staticmethod
    def is_enabled() -> bool:
        val = os.environ.get(RETENTION_MAINTENANCE_ENABLED_ENV, "true")
        return val.lower() in ("true", "1", "yes")

    @staticmethod
    def poll_interval_seconds() -> int:
        try:
            n = int(
                os.environ.get(
                    RETENTION_MAINTENANCE_INTERVAL_SECONDS_ENV,
                    str(DEFAULT_RETENTION_MAINTENANCE_INTERVAL_SECONDS),
                )
            )
            return n if n > 0 else DEFAULT_RETENTION_MAINTENANCE_INTERVAL_SECONDS
        except (TypeError, ValueError):
            return DEFAULT_RETENTION_MAINTENANCE_INTERVAL_SECONDS

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Retention maintenance runner started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Retention maintenance runner stopped")

    def get_status(self) -> dict:
        return {
            "enabled": self.is_enabled(),
            "running": self._running,
            "last_run_at": self._last_run_at,
            "poll_interval_seconds": self.poll_interval_seconds(),
        }

    async def run_once(self) -> dict:
        """Run one retention cycle in a worker thread."""
        from retention_policy import apply_retention

        result = await asyncio.to_thread(apply_retention)
        self._last_run_at = datetime.now(timezone.utc).isoformat()
        return result

    async def _loop(self) -> None:
        interval = self.poll_interval_seconds()
        while self._running:
            try:
                result = await self.run_once()
                if not result.get("ok", False):
                    logger.warning("Retention maintenance cycle failed: %s", result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Retention maintenance loop failed: %s", e)
            await asyncio.sleep(interval)


_runner: Optional[RetentionMaintenanceRunner] = None


def get_retention_maintenance_runner() -> RetentionMaintenanceRunner:
    global _runner
    if _runner is None:
        _runner = RetentionMaintenanceRunner()
    return _runner
