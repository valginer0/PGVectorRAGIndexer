"""
Server Scheduler module (#6b).

In-process background scheduler for server-scope watched folders.
Uses a PostgreSQL advisory lock to guarantee singleton execution
across multiple API replicas.

Enabled by SERVER_SCHEDULER_ENABLED=true (default: disabled).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# CRC32("pgvector_server_scheduler") → deterministic constant
SERVER_SCHEDULER_LOCK_ID = 2050923308

# Environment variable to enable the server scheduler
SERVER_SCHEDULER_ENABLED_ENV = "SERVER_SCHEDULER_ENABLED"

# Poll interval in seconds
POLL_INTERVAL = 60

# Maximum consecutive failures before backoff (skip root for 1 hour)
MAX_FAILURE_STREAK = 5
FAILURE_BACKOFF_SECONDS = 3600  # 1 hour

# Quarantine purge interval (once per 24h)
PURGE_INTERVAL_SECONDS = 86400


class ServerScheduler:
    """In-process scheduler for server-scope watched folders.

    Runs as an asyncio background task within the FastAPI process.
    Uses pg_try_advisory_lock for singleton guarantee.
    Wraps synchronous scan_folder() in asyncio.to_thread() to avoid
    blocking the event loop.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lease_held = False
        self._last_poll_at: Optional[str] = None
        self._last_purge_at: float = 0.0
        self._active_scans: int = 0

    @staticmethod
    def is_enabled() -> bool:
        """Check if the server scheduler is enabled via env var."""
        val = os.environ.get(SERVER_SCHEDULER_ENABLED_ENV, "false")
        return val.lower() in ("true", "1", "yes")

    async def start(self) -> None:
        """Start the scheduler background task."""
        if self._running:
            logger.warning("Server scheduler already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Server scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler and release the advisory lock."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._lease_held:
            await self._release_lease()
        logger.info("Server scheduler stopped")

    def get_status(self) -> dict:
        """Return current scheduler status for the admin API."""
        return {
            "enabled": self.is_enabled(),
            "running": self._running,
            "lease_held": self._lease_held,
            "last_poll_at": self._last_poll_at,
            "active_scans": self._active_scans,
            "poll_interval_seconds": POLL_INTERVAL,
        }

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop: acquire lease, poll, scan, purge."""
        while self._running:
            try:
                if not self._lease_held:
                    self._lease_held = await self._try_acquire_lease()
                    if not self._lease_held:
                        logger.debug(
                            "Could not acquire scheduler lease — "
                            "another instance holds it"
                        )
                        await asyncio.sleep(POLL_INTERVAL)
                        continue

                await self._run_pending_scans()

                # Periodic quarantine purge (once per 24h)
                await self._maybe_purge_quarantine()

                self._last_poll_at = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Server scheduler loop error: %s", e)

            await asyncio.sleep(POLL_INTERVAL)

    async def _try_acquire_lease(self) -> bool:
        """Attempt to acquire the advisory lock. Non-blocking."""
        try:
            from database import get_db_manager
            with get_db_manager().get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_try_advisory_lock(%s)", (SERVER_SCHEDULER_LOCK_ID,)
                )
                result = cur.fetchone()[0]
                return bool(result)
        except Exception as e:
            logger.debug("Failed to acquire advisory lock: %s", e)
            return False

    async def _release_lease(self) -> None:
        """Release the advisory lock."""
        try:
            from database import get_db_manager
            with get_db_manager().get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pg_advisory_unlock(%s)", (SERVER_SCHEDULER_LOCK_ID,)
                )
            self._lease_held = False
            logger.debug("Released advisory lock")
        except Exception as e:
            logger.debug("Failed to release advisory lock: %s", e)

    async def _run_pending_scans(self) -> None:
        """Find due server-scope roots and scan them."""
        from watched_folders import (
            list_folders,
            mark_scanned,
            update_scan_watermarks,
        )

        folders = list_folders(
            enabled_only=True,
            execution_scope="server",
        )

        now = time.time()

        for folder in folders:
            if folder.get("paused"):
                continue

            # Skip roots in failure backoff
            failures = folder.get("consecutive_failures", 0)
            if failures >= MAX_FAILURE_STREAK:
                last_error = folder.get("last_error_at")
                if last_error:
                    try:
                        if isinstance(last_error, str):
                            error_ts = datetime.fromisoformat(
                                last_error
                            ).timestamp()
                        else:
                            error_ts = last_error.timestamp()
                        if now - error_ts < FAILURE_BACKOFF_SECONDS:
                            logger.debug(
                                "Skipping root %s — in failure backoff "
                                "(%d consecutive failures)",
                                folder["id"], failures,
                            )
                            continue
                    except (ValueError, OSError):
                        pass

            # Check if scan is due based on cron schedule
            if not self._is_scan_due(folder):
                continue

            # Run the scan
            await self._run_scan(folder)

    def _is_scan_due(self, folder: dict) -> bool:
        """Check if a folder is due for scanning based on its cron schedule.

        Simple interval-based check: compare last_scanned_at against
        the cron interval. For MVP, we parse common cron patterns.
        """
        last_scanned = folder.get("last_scanned_at")
        if not last_scanned:
            return True  # Never scanned

        try:
            if isinstance(last_scanned, str):
                last_ts = datetime.fromisoformat(last_scanned).timestamp()
            else:
                last_ts = last_scanned.timestamp()

            interval = self._cron_to_seconds(folder.get("schedule_cron", ""))
            return time.time() - last_ts >= interval
        except (ValueError, OSError):
            return True  # On parse error, scan anyway

    @staticmethod
    def _cron_to_seconds(cron: str) -> int:
        """Convert common cron patterns to an interval in seconds.

        Handles: '0 */N * * *' (every N hours), '*/N * * * *' (every N min).
        Falls back to 6 hours for unrecognized patterns.
        """
        parts = cron.strip().split()
        if len(parts) < 5:
            return 6 * 3600  # Default 6 hours

        try:
            # Every N hours: '0 */N * * *'
            if parts[1].startswith("*/"):
                hours = int(parts[1][2:])
                return hours * 3600
            # Every N minutes: '*/N * * * *'
            if parts[0].startswith("*/"):
                minutes = int(parts[0][2:])
                return minutes * 60
        except (ValueError, IndexError):
            pass

        return 6 * 3600  # Default fallback

    async def _run_scan(self, folder: dict) -> dict:
        """Run a folder scan in a thread pool to avoid blocking the event loop."""
        from watched_folders import scan_folder, mark_scanned, update_scan_watermarks

        folder_id = folder["id"]
        folder_path = folder["folder_path"]

        logger.info(
            "Server scheduler: scanning root %s (%s)",
            folder_id, folder_path,
        )

        # Mark scan started
        update_scan_watermarks(folder_id, started=True)
        self._active_scans += 1

        try:
            result = await asyncio.to_thread(
                scan_folder, folder_path, None, folder.get("root_id"),
            )

            # Update watermarks based on result
            scan_status = result.get("status", "failed")
            update_scan_watermarks(
                folder_id,
                completed=True,
                success=(scan_status in ("success", "partial")),
                error=(scan_status == "failed"),
            )

            # Update legacy last_scanned_at
            if result.get("run_id"):
                mark_scanned(folder_id, run_id=result["run_id"])

            logger.info(
                "Server scheduler: scan complete for %s — %s "
                "(files: %d scanned, %d added, %d failed)",
                folder_id, scan_status,
                result.get("files_scanned", 0),
                result.get("files_added", 0),
                result.get("files_failed", 0),
            )
            return result
        except Exception as e:
            logger.error(
                "Server scheduler: scan failed for %s: %s", folder_id, e
            )
            update_scan_watermarks(folder_id, completed=True, error=True)
            return {"status": "failed", "error": str(e)}
        finally:
            self._active_scans -= 1

    async def _maybe_purge_quarantine(self) -> None:
        """Purge expired quarantined chunks if enough time has elapsed."""
        now = time.time()
        if now - self._last_purge_at < PURGE_INTERVAL_SECONDS:
            return

        try:
            from quarantine import purge_expired
            count = await asyncio.to_thread(purge_expired)
            self._last_purge_at = now
            if count > 0:
                logger.info("Server scheduler: purged %d expired quarantined chunks", count)
        except Exception as e:
            logger.warning("Server scheduler: quarantine purge failed: %s", e)

    async def scan_root_now(self, root_id: str) -> dict:
        """Trigger an immediate scan of a server-scope root by root_id.

        Used by the scan-now admin endpoint.
        """
        from watched_folders import get_folder_by_root_id

        folder = get_folder_by_root_id(root_id)
        if not folder:
            return {"ok": False, "error": "Root not found"}
        if folder.get("execution_scope") != "server":
            return {"ok": False, "error": "Root is not server-scope"}

        result = await self._run_scan(folder)
        return {"ok": True, "scan_result": result}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_scheduler: Optional[ServerScheduler] = None


def get_server_scheduler() -> ServerScheduler:
    """Get (or create) the module-level server scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ServerScheduler()
    return _scheduler
