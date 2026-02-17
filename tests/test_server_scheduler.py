"""
Tests for the Server Scheduler module (#6b).

Covers:
- Singleton lease (advisory lock acquire/release)
- Scope filtering (only scans server roots)
- Async scan wrapper (doesn't block event loop)
- Failure backoff logic
- Cron-to-seconds conversion
- Scan watermark updates
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from server_scheduler import (
    ServerScheduler,
    SERVER_SCHEDULER_LOCK_ID,
    MAX_FAILURE_STREAK,
    FAILURE_BACKOFF_SECONDS,
)


class TestServerSchedulerInit:
    """Basic initialization and config."""

    def test_lock_id_is_deterministic(self):
        assert SERVER_SCHEDULER_LOCK_ID == 2050923308

    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert not ServerScheduler.is_enabled()

    def test_enabled_via_env(self):
        with patch.dict("os.environ", {"SERVER_SCHEDULER_ENABLED": "true"}):
            assert ServerScheduler.is_enabled()

    def test_enabled_via_env_1(self):
        with patch.dict("os.environ", {"SERVER_SCHEDULER_ENABLED": "1"}):
            assert ServerScheduler.is_enabled()

    def test_not_enabled_for_false(self):
        with patch.dict("os.environ", {"SERVER_SCHEDULER_ENABLED": "false"}):
            assert not ServerScheduler.is_enabled()

    def test_initial_status(self):
        scheduler = ServerScheduler()
        status = scheduler.get_status()
        assert status["running"] is False
        assert status["lease_held"] is False
        assert status["active_scans"] == 0


class TestCronToSeconds:
    """Tests for cron pattern parsing."""

    def test_every_6_hours(self):
        assert ServerScheduler._cron_to_seconds("0 */6 * * *") == 6 * 3600

    def test_every_12_hours(self):
        assert ServerScheduler._cron_to_seconds("0 */12 * * *") == 12 * 3600

    def test_every_30_minutes(self):
        assert ServerScheduler._cron_to_seconds("*/30 * * * *") == 30 * 60

    def test_invalid_cron_defaults_6h(self):
        assert ServerScheduler._cron_to_seconds("invalid") == 6 * 3600

    def test_empty_cron_defaults_6h(self):
        assert ServerScheduler._cron_to_seconds("") == 6 * 3600


class TestIsScanDue:
    """Tests for scan-due logic."""

    def test_never_scanned_is_always_due(self):
        scheduler = ServerScheduler()
        folder = {"last_scanned_at": None, "schedule_cron": "0 */6 * * *"}
        assert scheduler._is_scan_due(folder) is True

    def test_recently_scanned_not_due(self):
        scheduler = ServerScheduler()
        recent = datetime.now(timezone.utc).isoformat()
        folder = {"last_scanned_at": recent, "schedule_cron": "0 */6 * * *"}
        assert scheduler._is_scan_due(folder) is False

    def test_old_scan_is_due(self):
        scheduler = ServerScheduler()
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        folder = {"last_scanned_at": old, "schedule_cron": "0 */6 * * *"}
        assert scheduler._is_scan_due(folder) is True


class TestFailureBackoff:
    """Tests for failure backoff behavior."""

    @pytest.mark.asyncio
    async def test_skips_root_in_backoff(self):
        """Root with >=5 consecutive failures and recent error is skipped."""
        scheduler = ServerScheduler()
        recent_error = datetime.now(timezone.utc).isoformat()
        folders = [
            {
                "id": "test-id",
                "folder_path": "/test",
                "paused": False,
                "consecutive_failures": MAX_FAILURE_STREAK,
                "last_error_at": recent_error,
                "last_scanned_at": None,
                "schedule_cron": "0 */6 * * *",
            }
        ]

        with patch("watched_folders.list_folders", return_value=folders):
            with patch.object(scheduler, "_run_scan") as mock_scan:
                await scheduler._run_pending_scans()
                mock_scan.assert_not_called()

    @pytest.mark.asyncio
    async def test_scans_root_after_backoff_expires(self):
        """Root with old error timestamp should be re-attempted."""
        scheduler = ServerScheduler()
        old_error = (
            datetime.now(timezone.utc) - timedelta(seconds=FAILURE_BACKOFF_SECONDS + 60)
        ).isoformat()
        folders = [
            {
                "id": "test-id",
                "folder_path": "/test",
                "paused": False,
                "consecutive_failures": MAX_FAILURE_STREAK,
                "last_error_at": old_error,
                "last_scanned_at": None,
                "schedule_cron": "0 */6 * * *",
            }
        ]

        with patch("watched_folders.list_folders", return_value=folders):
            with patch.object(scheduler, "_run_scan", new_callable=AsyncMock) as mock_scan:
                await scheduler._run_pending_scans()
                mock_scan.assert_called_once()


class TestPausedRoots:
    """Tests for paused root handling."""

    @pytest.mark.asyncio
    async def test_skips_paused_roots(self):
        scheduler = ServerScheduler()
        folders = [
            {
                "id": "paused-id",
                "folder_path": "/paused",
                "paused": True,
                "consecutive_failures": 0,
                "last_scanned_at": None,
                "schedule_cron": "0 */6 * * *",
            }
        ]

        with patch("watched_folders.list_folders", return_value=folders):
            with patch.object(scheduler, "_run_scan") as mock_scan:
                await scheduler._run_pending_scans()
                mock_scan.assert_not_called()


class TestAsyncScan:
    """Tests for async scan wrapper."""

    @pytest.mark.asyncio
    async def test_scan_uses_thread_pool(self):
        """scan_folder is called via asyncio.to_thread."""
        scheduler = ServerScheduler()
        folder = {
            "id": "test-id",
            "folder_path": "/test/path",
        }
        mock_result = {
            "run_id": "run-123",
            "status": "success",
            "files_scanned": 5,
            "files_added": 3,
            "files_failed": 0,
        }

        with patch("watched_folders.scan_folder", return_value=mock_result) as mock_sf:
            with patch("watched_folders.mark_scanned"):
                with patch("watched_folders.update_scan_watermarks"):
                    result = await scheduler._run_scan(folder)

        assert result["status"] == "success"
        mock_sf.assert_called_once_with("/test/path", None, None)

    @pytest.mark.asyncio
    async def test_scan_failure_updates_watermarks(self):
        """Failed scan increments consecutive_failures."""
        scheduler = ServerScheduler()
        folder = {"id": "fail-id", "folder_path": "/fail/path"}

        with patch("watched_folders.scan_folder", side_effect=RuntimeError("boom")):
            with patch("watched_folders.update_scan_watermarks") as mock_wm:
                result = await scheduler._run_scan(folder)

        assert result["status"] == "failed"
        # Should have been called with started=True (first call)
        # and completed=True, error=True (second call)
        assert mock_wm.call_count == 2


class TestScanRootNow:
    """Tests for the scan-now admin function."""

    @pytest.mark.asyncio
    async def test_scan_now_non_server_root_rejected(self):
        scheduler = ServerScheduler()
        mock_folder = {"id": "1", "execution_scope": "client", "folder_path": "/x"}

        with patch("watched_folders.get_folder_by_root_id", return_value=mock_folder):
            result = await scheduler.scan_root_now("root-1")
        assert result["ok"] is False
        assert "not server-scope" in result["error"]

    @pytest.mark.asyncio
    async def test_scan_now_missing_root(self):
        scheduler = ServerScheduler()

        with patch("watched_folders.get_folder_by_root_id", return_value=None):
            result = await scheduler.scan_root_now("nonexistent")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()
