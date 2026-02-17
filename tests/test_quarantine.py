"""Tests for Phase 6b.3: Quarantine Delete Lifecycle + Dry-Run.

Covers:
  - Quarantine / restore round-trip
  - Retention purge (only deletes chunks older than window)
  - Quarantine stats
  - Dry-run scan report (no DB mutations)
  - _quarantine_missing_sources flow
  - Server scheduler periodic purge
  - Migration 015 metadata
"""

import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ── Quarantine module ──────────────────────────────────────────────────────


class TestQuarantineChunks:
    """quarantine_chunks() marks chunks as quarantined."""

    @patch("quarantine._get_db_connection")
    def test_quarantine_sets_timestamp(self, mock_conn):
        from quarantine import quarantine_chunks

        mock_cur = MagicMock()
        mock_cur.rowcount = 3
        mock_conn.return_value.cursor.return_value = mock_cur

        count = quarantine_chunks("/data/docs/readme.md", "source_file_missing")

        assert count == 3
        # Verify UPDATE was called with reason and source_uri
        call_args = mock_cur.execute.call_args
        assert "quarantined_at" in call_args[0][0]
        assert "source_file_missing" in call_args[0][1]

    @patch("quarantine._get_db_connection")
    def test_quarantine_skips_already_quarantined(self, mock_conn):
        from quarantine import quarantine_chunks

        mock_cur = MagicMock()
        mock_cur.rowcount = 0
        mock_conn.return_value.cursor.return_value = mock_cur

        count = quarantine_chunks("/data/docs/already.md")
        assert count == 0


class TestRestoreChunks:
    """restore_chunks() removes quarantine status."""

    @patch("quarantine._get_db_connection")
    def test_restore_clears_quarantine(self, mock_conn):
        from quarantine import restore_chunks

        mock_cur = MagicMock()
        mock_cur.rowcount = 2
        mock_conn.return_value.cursor.return_value = mock_cur

        count = restore_chunks("/data/docs/readme.md")

        assert count == 2
        call_args = mock_cur.execute.call_args
        assert "quarantined_at = NULL" in call_args[0][0]

    @patch("quarantine._get_db_connection")
    def test_restore_no_quarantined(self, mock_conn):
        from quarantine import restore_chunks

        mock_cur = MagicMock()
        mock_cur.rowcount = 0
        mock_conn.return_value.cursor.return_value = mock_cur

        count = restore_chunks("/data/docs/not_quarantined.md")
        assert count == 0


class TestQuarantineRoundTrip:
    """Quarantine → restore round-trip."""

    @patch("quarantine._get_db_connection")
    def test_quarantine_then_restore(self, mock_conn):
        from quarantine import quarantine_chunks, restore_chunks

        mock_cur = MagicMock()
        mock_cur.rowcount = 5
        mock_conn.return_value.cursor.return_value = mock_cur

        quarantined = quarantine_chunks("/data/docs/file.md")
        assert quarantined == 5

        restored = restore_chunks("/data/docs/file.md")
        assert restored == 5


class TestPurgeExpired:
    """purge_expired() deletes old quarantined chunks."""

    @patch("quarantine._get_db_connection")
    def test_purge_deletes_old_chunks(self, mock_conn):
        from quarantine import purge_expired

        mock_cur = MagicMock()
        mock_cur.rowcount = 10
        mock_conn.return_value.cursor.return_value = mock_cur

        count = purge_expired(retention_days=30)

        assert count == 10
        call_args = mock_cur.execute.call_args
        assert "DELETE" in call_args[0][0]

    @patch("quarantine._get_db_connection")
    def test_purge_respects_retention_days(self, mock_conn):
        from quarantine import purge_expired

        mock_cur = MagicMock()
        mock_cur.rowcount = 0
        mock_conn.return_value.cursor.return_value = mock_cur

        count = purge_expired(retention_days=7)

        assert count == 0
        call_args = mock_cur.execute.call_args
        assert 7 in call_args[0][1]

    def test_get_retention_days_default(self):
        from quarantine import get_retention_days
        with patch.dict("os.environ", {}, clear=True):
            assert get_retention_days() == 30

    def test_get_retention_days_from_env(self):
        from quarantine import get_retention_days
        with patch.dict("os.environ", {"QUARANTINE_RETENTION_DAYS": "7"}):
            assert get_retention_days() == 7


class TestQuarantineStats:
    """get_quarantine_stats() returns summary info."""

    @patch("quarantine._get_db_connection")
    def test_stats_with_data(self, mock_conn):
        from quarantine import get_quarantine_stats

        mock_cur = MagicMock()
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_cur.fetchone.return_value = (5, 25, ts)
        mock_conn.return_value.cursor.return_value = mock_cur

        stats = get_quarantine_stats()

        assert stats["total_documents"] == 5
        assert stats["total_chunks"] == 25
        assert stats["oldest_quarantine_at"] == ts.isoformat()

    @patch("quarantine._get_db_connection")
    def test_stats_empty(self, mock_conn):
        from quarantine import get_quarantine_stats

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0, 0, None)
        mock_conn.return_value.cursor.return_value = mock_cur

        stats = get_quarantine_stats()

        assert stats["total_documents"] == 0
        assert stats["total_chunks"] == 0
        assert stats["oldest_quarantine_at"] is None


class TestListQuarantined:
    """list_quarantined() returns paginated results."""

    @patch("quarantine._get_db_connection")
    def test_list_returns_grouped(self, mock_conn):
        from quarantine import list_quarantined

        ts = datetime(2025, 6, 15, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("/data/file1.md", 3, ts, "source_file_missing"),
            ("/data/file2.md", 1, ts, "source_file_missing"),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        results = list_quarantined(limit=10, offset=0)

        assert len(results) == 2
        assert results[0]["source_uri"] == "/data/file1.md"
        assert results[0]["chunk_count"] == 3

    @patch("quarantine._get_db_connection")
    def test_list_empty(self, mock_conn):
        from quarantine import list_quarantined

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cur

        results = list_quarantined()
        assert results == []


# ── Dry-Run Scan ───────────────────────────────────────────────────────────


class TestDryRunScan:
    """dry_run scan mode reports without mutations."""

    @patch("watched_folders._get_db_connection")
    @patch("os.walk", return_value=[("/data/docs", [], ["a.txt", "b.md"])])
    @patch("os.path.isdir", return_value=True)
    def test_dry_run_lists_files(self, mock_isdir, mock_walk, mock_conn):
        from watched_folders import scan_folder

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []  # No indexed files
        mock_conn.return_value.cursor.return_value = mock_cur

        result = scan_folder("/data/docs", dry_run=True)

        assert result["dry_run"] is True
        assert result["status"] == "success"
        assert result["total_files"] == 2
        assert len(result["would_index"]) == 2

    @patch("watched_folders._get_db_connection")
    @patch("os.walk", return_value=[("/data/docs", [], ["a.txt"])])
    @patch("os.path.isdir", return_value=True)
    def test_dry_run_detects_would_quarantine(self, mock_isdir, mock_walk, mock_conn):
        from watched_folders import scan_folder

        mock_cur = MagicMock()
        # Simulate an indexed file that no longer exists on disk
        mock_cur.fetchall.return_value = [
            ("/data/docs/deleted.md",),
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        result = scan_folder("/data/docs", dry_run=True)

        assert result["dry_run"] is True
        assert "/data/docs/deleted.md" in result["would_quarantine"]

    @patch("os.path.isdir", return_value=False)
    def test_dry_run_missing_directory(self, mock_isdir):
        from watched_folders import scan_folder

        result = scan_folder("/nonexistent", dry_run=True)

        assert result["dry_run"] is True
        assert result["status"] == "failed"
        assert "not found" in result["error"].lower()


# ── Quarantine Integration in scan_folder ──────────────────────────────────


class TestQuarantineMissingSources:
    """_quarantine_missing_sources() quarantines/restores based on file existence."""

    @patch("watched_folders._get_db_connection")
    @patch("os.path.isfile")
    def test_quarantines_missing_files(self, mock_isfile, mock_conn):
        from watched_folders import _quarantine_missing_sources

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("/data/docs/missing.md", False),  # Not already quarantined
        ]
        mock_conn.return_value.cursor.return_value = mock_cur
        mock_isfile.return_value = False  # File doesn't exist

        with patch("quarantine.quarantine_chunks") as mock_q:
            _quarantine_missing_sources("/data/docs")
            mock_q.assert_called_once_with("/data/docs/missing.md", "source_file_missing")

    @patch("watched_folders._get_db_connection")
    @patch("os.path.isfile")
    def test_restores_reappeared_files(self, mock_isfile, mock_conn):
        from watched_folders import _quarantine_missing_sources

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("/data/docs/back.md", True),  # Already quarantined
        ]
        mock_conn.return_value.cursor.return_value = mock_cur
        mock_isfile.return_value = True  # File reappeared

        with patch("quarantine.restore_chunks") as mock_r:
            _quarantine_missing_sources("/data/docs")
            mock_r.assert_called_once_with("/data/docs/back.md")

    @patch("watched_folders._get_db_connection")
    @patch("os.path.isfile")
    def test_no_action_for_existing_files(self, mock_isfile, mock_conn):
        from watched_folders import _quarantine_missing_sources

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("/data/docs/ok.md", False),  # Not quarantined, file exists
        ]
        mock_conn.return_value.cursor.return_value = mock_cur
        mock_isfile.return_value = True

        with patch("quarantine.quarantine_chunks") as mock_q:
            with patch("quarantine.restore_chunks") as mock_r:
                _quarantine_missing_sources("/data/docs")
                mock_q.assert_not_called()
                mock_r.assert_not_called()


# ── Server Scheduler Purge ─────────────────────────────────────────────────


class TestSchedulerQuarantinePurge:
    """Server scheduler periodically purges expired quarantined chunks."""

    @pytest.mark.asyncio
    async def test_purge_runs_when_due(self):
        from server_scheduler import ServerScheduler

        scheduler = ServerScheduler()
        scheduler._last_purge_at = 0.0  # Force purge to be due

        with patch("quarantine.purge_expired", return_value=5) as mock_purge:
            await scheduler._maybe_purge_quarantine()

        mock_purge.assert_called_once()
        assert scheduler._last_purge_at > 0

    @pytest.mark.asyncio
    async def test_purge_skips_when_recent(self):
        from server_scheduler import ServerScheduler

        scheduler = ServerScheduler()
        scheduler._last_purge_at = time.time()  # Just purged

        with patch("quarantine.purge_expired") as mock_purge:
            await scheduler._maybe_purge_quarantine()

        mock_purge.assert_not_called()


# ── Migration 015 metadata ────────────────────────────────────────────────


class TestMigration015Metadata:
    """Basic structural checks for migration 015."""

    def test_revision_chain(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_015",
            "/home/valginer0/projects/PGVectorRAGIndexer/alembic/versions/015_quarantine.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "015"
        assert mod.down_revision == "014"

    def test_has_upgrade_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_015",
            "/home/valginer0/projects/PGVectorRAGIndexer/alembic/versions/015_quarantine.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
