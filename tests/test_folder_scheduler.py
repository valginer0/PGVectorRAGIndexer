"""
Tests for the in-app FolderScheduler (#6).

Tests cover:
- _cron_is_due helper (various cron patterns, never-scanned, edge cases)
- FolderScheduler lifecycle (start/stop, is_running)
- FolderScheduler._check_folders logic
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: _cron_is_due
# ===========================================================================


class TestCronIsDue:
    def test_never_scanned_is_always_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        assert _cron_is_due("0 */6 * * *", None) is True

    def test_recently_scanned_not_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        now = datetime.now(timezone.utc).isoformat()
        assert _cron_is_due("0 */6 * * *", now) is False

    def test_old_scan_is_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        assert _cron_is_due("0 */6 * * *", old) is True

    def test_every_hour(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        assert _cron_is_due("0 * * * *", old) is True

    def test_every_hour_not_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        assert _cron_is_due("0 * * * *", recent) is False

    def test_daily_midnight(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        assert _cron_is_due("0 0 * * *", old) is True

    def test_daily_not_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        recent = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        assert _cron_is_due("0 0 * * *", recent) is False

    def test_invalid_cron_returns_false(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        assert _cron_is_due("bad", "2026-01-01T00:00:00+00:00") is False

    def test_every_3_hours(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        old = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        assert _cron_is_due("0 */3 * * *", old) is True

    def test_every_12_hours_not_due(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        assert _cron_is_due("0 */12 * * *", recent) is False

    def test_z_suffix_timestamp(self):
        from desktop_app.utils.folder_scheduler import _cron_is_due
        old = (datetime.now(timezone.utc) - timedelta(hours=7))
        ts = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _cron_is_due("0 */6 * * *", ts) is True


# ===========================================================================
# Test: FolderScheduler lifecycle
# ===========================================================================


class TestFolderSchedulerLifecycle:
    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.list_watched_folders.return_value = {"folders": [], "count": 0}
        return api

    def test_not_running_by_default(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        assert sched.is_running is False

    def test_start_sets_running(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        sched.start()
        assert sched.is_running is True
        sched.stop()

    def test_stop_clears_running(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        sched.start()
        sched.stop()
        assert sched.is_running is False

    def test_double_start_no_error(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        sched.start()
        sched.start()  # Should not error
        assert sched.is_running is True
        sched.stop()

    def test_double_stop_no_error(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        sched.stop()  # Not running, should not error
        assert sched.is_running is False

    def test_set_client_id(self, mock_api):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        sched = FolderScheduler(mock_api)
        sched.set_client_id("test-id")
        assert sched._client_id == "test-id"


# ===========================================================================
# Test: _check_folders logic
# ===========================================================================


class TestCheckFolders:
    def test_skips_not_due_folders(self):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        api = MagicMock()
        now = datetime.now(timezone.utc).isoformat()
        api.list_watched_folders.return_value = {
            "folders": [
                {"id": "f1", "folder_path": "/data", "schedule_cron": "0 */6 * * *",
                 "last_scanned_at": now, "enabled": True}
            ],
            "count": 1,
        }
        sched = FolderScheduler(api)
        sched._check_folders()
        api.scan_watched_folder.assert_not_called()

    def test_scans_due_folders(self):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        api = MagicMock()
        api.scan_watched_folder.return_value = {"status": "success", "run_id": "r1"}
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        api.list_watched_folders.return_value = {
            "folders": [
                {"id": "f1", "folder_path": "/data", "schedule_cron": "0 */6 * * *",
                 "last_scanned_at": old, "enabled": True}
            ],
            "count": 1,
        }
        sched = FolderScheduler(api)
        sched._check_folders()
        api.scan_watched_folder.assert_called_once_with("f1", client_id=None)

    def test_scans_never_scanned_folder(self):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        api = MagicMock()
        api.scan_watched_folder.return_value = {"status": "success", "run_id": "r1"}
        api.list_watched_folders.return_value = {
            "folders": [
                {"id": "f2", "folder_path": "/new", "schedule_cron": "0 */6 * * *",
                 "last_scanned_at": None, "enabled": True}
            ],
            "count": 1,
        }
        sched = FolderScheduler(api)
        sched._check_folders()
        api.scan_watched_folder.assert_called_once()

    def test_api_failure_does_not_crash(self):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        api = MagicMock()
        api.list_watched_folders.side_effect = Exception("Network error")
        sched = FolderScheduler(api)
        sched._check_folders()  # Should not raise

    def test_passes_client_id(self):
        from desktop_app.utils.folder_scheduler import FolderScheduler
        api = MagicMock()
        api.scan_watched_folder.return_value = {"status": "success", "run_id": "r1"}
        api.list_watched_folders.return_value = {
            "folders": [
                {"id": "f1", "folder_path": "/data", "schedule_cron": "0 */6 * * *",
                 "last_scanned_at": None, "enabled": True}
            ],
            "count": 1,
        }
        sched = FolderScheduler(api)
        sched.set_client_id("my-client")
        sched._check_folders()
        api.scan_watched_folder.assert_called_once_with("f1", client_id="my-client")
