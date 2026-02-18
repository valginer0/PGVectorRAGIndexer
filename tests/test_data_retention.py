"""Tests for data retention policies.

Covers:
  - Migration 017 metadata
  - retention_policy defaults (activity_log 2555d, indexing_runs 10950d, quarantine 30d)
  - Env var overrides
  - apply_retention orchestration
  - Indexing runs safety: terminal states only, never active rows
  - Retention maintenance runner lifecycle
  - API endpoint wiring
"""

import importlib.util
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ── Migration 017 metadata ────────────────────────────────────────────────


class TestMigration017Metadata:
    """Basic structural checks for migration 017."""

    def _load_migration(self):
        spec = importlib.util.spec_from_file_location(
            "migration_017",
            "/home/valginer0/projects/PGVectorRAGIndexer/alembic/versions/017_retention_policies.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_revision_chain(self):
        mod = self._load_migration()
        assert mod.revision == "017"
        assert mod.down_revision == "016"

    def test_has_upgrade_downgrade(self):
        mod = self._load_migration()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


# ── Policy defaults ───────────────────────────────────────────────────────


class TestPolicyDefaults:
    """get_policy_defaults returns correct category defaults."""

    @patch("quarantine.get_retention_days", return_value=30)
    def test_default_values(self, mock_qrt):
        from retention_policy import get_policy_defaults

        with patch.dict("os.environ", {}, clear=False):
            # Remove any env overrides that might be set
            import os
            old_act = os.environ.pop("ACTIVITY_RETENTION_DAYS", None)
            old_idx = os.environ.pop("INDEXING_RUNS_RETENTION_DAYS", None)
            try:
                defaults = get_policy_defaults()
            finally:
                if old_act is not None:
                    os.environ["ACTIVITY_RETENTION_DAYS"] = old_act
                if old_idx is not None:
                    os.environ["INDEXING_RUNS_RETENTION_DAYS"] = old_idx

        assert defaults["activity_days"] == 2555
        assert defaults["quarantine_days"] == 30
        assert defaults["indexing_runs_days"] == 10950
        assert defaults["saml_sessions"] == "expiry_only"

    @patch("quarantine.get_retention_days", return_value=30)
    def test_env_var_override_activity(self, mock_qrt):
        from retention_policy import get_policy_defaults

        with patch.dict("os.environ", {"ACTIVITY_RETENTION_DAYS": "90"}):
            defaults = get_policy_defaults()

        assert defaults["activity_days"] == 90

    @patch("quarantine.get_retention_days", return_value=30)
    def test_env_var_override_indexing_runs(self, mock_qrt):
        from retention_policy import get_policy_defaults

        with patch.dict("os.environ", {"INDEXING_RUNS_RETENTION_DAYS": "180"}):
            defaults = get_policy_defaults()

        assert defaults["indexing_runs_days"] == 180

    @patch("quarantine.get_retention_days", return_value=7)
    def test_quarantine_days_from_quarantine_module(self, mock_qrt):
        from retention_policy import get_policy_defaults

        defaults = get_policy_defaults()
        assert defaults["quarantine_days"] == 7


# ── apply_retention orchestration ──────────────────────────────────────────


class TestApplyRetention:
    """apply_retention delegates to per-category functions."""

    @patch("saml_auth.cleanup_expired_sessions", return_value=5)
    @patch("indexing_runs.apply_retention", return_value=10)
    @patch("quarantine.purge_expired", return_value=3)
    @patch("activity_log.apply_retention", return_value=20)
    @patch("quarantine.get_retention_days", return_value=30)
    def test_orchestration_with_defaults(
        self, mock_qrt_days, mock_act, mock_qrt, mock_idx, mock_saml,
    ):
        from retention_policy import apply_retention

        result = apply_retention()

        assert result["ok"] is True
        assert result["activity_deleted"] == 20
        assert result["quarantine_purged"] == 3
        assert result["indexing_runs_deleted"] == 10
        assert result["saml_sessions_deleted"] == 5

        mock_act.assert_called_once_with(2555)
        mock_qrt.assert_called_once_with(retention_days=30)
        mock_idx.assert_called_once_with(10950)

    @patch("saml_auth.cleanup_expired_sessions", return_value=0)
    @patch("indexing_runs.apply_retention", return_value=0)
    @patch("quarantine.purge_expired", return_value=0)
    @patch("activity_log.apply_retention", return_value=0)
    @patch("quarantine.get_retention_days", return_value=30)
    def test_per_category_override(
        self, mock_qrt_days, mock_act, mock_qrt, mock_idx, mock_saml,
    ):
        from retention_policy import apply_retention

        apply_retention(activity_days=90, quarantine_days=7)

        mock_act.assert_called_once_with(90)
        mock_qrt.assert_called_once_with(retention_days=7)
        mock_idx.assert_called_once_with(10950)  # no override, uses default

    @patch("saml_auth.cleanup_expired_sessions")
    @patch("indexing_runs.apply_retention", return_value=0)
    @patch("quarantine.purge_expired", return_value=0)
    @patch("activity_log.apply_retention", return_value=0)
    @patch("quarantine.get_retention_days", return_value=30)
    def test_saml_skipped_when_disabled(
        self, mock_qrt_days, mock_act, mock_qrt, mock_idx, mock_saml,
    ):
        from retention_policy import apply_retention

        result = apply_retention(cleanup_saml_sessions=False)

        mock_saml.assert_not_called()
        assert result["saml_sessions_deleted"] == 0

    @patch("activity_log.apply_retention", side_effect=Exception("DB gone"))
    @patch("quarantine.get_retention_days", return_value=30)
    def test_error_sets_ok_false(self, mock_qrt_days, mock_act):
        from retention_policy import apply_retention

        result = apply_retention()

        assert result["ok"] is False
        assert "DB gone" in result.get("error", "")


# ── Indexing runs safety ──────────────────────────────────────────────────


class TestIndexingRunsSafety:
    """apply_retention in indexing_runs only deletes terminal states."""

    @patch("indexing_runs.get_db_manager")
    def test_only_terminal_status_deleted(self, mock_db):
        from indexing_runs import apply_retention

        mock_cur = MagicMock()
        mock_cur.rowcount = 5
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_db.return_value.get_connection.return_value = mock_conn

        deleted = apply_retention(365)

        assert deleted == 5
        call_args = mock_cur.execute.call_args[0]
        sql = call_args[0]
        # Verify safety predicates in SQL
        assert "success" in sql
        assert "partial" in sql
        assert "failed" in sql
        assert "COALESCE(completed_at, started_at)" in sql


# ── Retention maintenance runner ──────────────────────────────────────────


class TestRetentionMaintenanceRunner:
    """RetentionMaintenanceRunner lifecycle and configuration."""

    def test_default_enabled(self):
        from retention_maintenance import RetentionMaintenanceRunner

        with patch.dict("os.environ", {}, clear=False):
            import os
            old = os.environ.pop("RETENTION_MAINTENANCE_ENABLED", None)
            try:
                assert RetentionMaintenanceRunner.is_enabled() is True
            finally:
                if old is not None:
                    os.environ["RETENTION_MAINTENANCE_ENABLED"] = old

    def test_disabled_by_env(self):
        from retention_maintenance import RetentionMaintenanceRunner

        with patch.dict("os.environ", {"RETENTION_MAINTENANCE_ENABLED": "false"}):
            assert RetentionMaintenanceRunner.is_enabled() is False

    def test_default_interval(self):
        from retention_maintenance import RetentionMaintenanceRunner

        with patch.dict("os.environ", {}, clear=False):
            import os
            old = os.environ.pop("RETENTION_MAINTENANCE_INTERVAL_SECONDS", None)
            try:
                assert RetentionMaintenanceRunner.poll_interval_seconds() == 86400
            finally:
                if old is not None:
                    os.environ["RETENTION_MAINTENANCE_INTERVAL_SECONDS"] = old

    def test_custom_interval(self):
        from retention_maintenance import RetentionMaintenanceRunner

        with patch.dict("os.environ", {"RETENTION_MAINTENANCE_INTERVAL_SECONDS": "3600"}):
            assert RetentionMaintenanceRunner.poll_interval_seconds() == 3600

    def test_get_status_structure(self):
        from retention_maintenance import RetentionMaintenanceRunner

        runner = RetentionMaintenanceRunner()
        status = runner.get_status()

        assert "enabled" in status
        assert "running" in status
        assert "last_run_at" in status
        assert "poll_interval_seconds" in status
        assert status["running"] is False

    def test_singleton_getter(self):
        from retention_maintenance import get_retention_maintenance_runner
        import retention_maintenance

        retention_maintenance._runner = None  # reset
        runner1 = get_retention_maintenance_runner()
        runner2 = get_retention_maintenance_runner()
        assert runner1 is runner2

    @pytest.mark.asyncio
    async def test_start_stop(self):
        from retention_maintenance import RetentionMaintenanceRunner

        runner = RetentionMaintenanceRunner()
        with patch.object(runner, "_loop", new_callable=AsyncMock):
            await runner.start()
            assert runner._running is True
            await runner.stop()
            assert runner._running is False


# ── API wiring ────────────────────────────────────────────────────────────


class TestRetentionAPIWiring:
    """API endpoints correctly import from retention_policy."""

    @pytest.mark.asyncio
    async def test_get_retention_policy_endpoint(self):
        from api import get_retention_policy

        with patch("retention_policy.get_policy_defaults") as mock_defaults:
            mock_defaults.return_value = {"activity_days": 2555}
            result = await get_retention_policy()

        assert result["policy"]["activity_days"] == 2555

    @pytest.mark.asyncio
    async def test_run_retention_policy_endpoint(self):
        from api import run_retention_policy, RetentionRunRequest

        req = RetentionRunRequest(activity_days=90, cleanup_saml_sessions=False)

        with patch("retention_policy.apply_retention") as mock_apply:
            mock_apply.return_value = {
                "ok": True,
                "activity_deleted": 5,
                "quarantine_purged": 0,
                "indexing_runs_deleted": 0,
                "saml_sessions_deleted": 0,
            }
            result = await run_retention_policy(req)

        assert result["ok"] is True
        assert result["activity_deleted"] == 5

    @pytest.mark.asyncio
    async def test_get_retention_status_endpoint(self):
        from api import get_retention_status

        mock_runner = MagicMock()
        mock_runner.get_status.return_value = {
            "enabled": True,
            "running": True,
            "last_run_at": None,
            "poll_interval_seconds": 86400,
        }

        with patch("retention_maintenance.get_retention_maintenance_runner", return_value=mock_runner):
            result = await get_retention_status()

        assert result["enabled"] is True
        assert result["poll_interval_seconds"] == 86400
