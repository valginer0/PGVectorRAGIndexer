"""Tests for retention policy orchestration."""

import os
import sys
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPolicyDefaults:
    @patch("quarantine.get_retention_days", return_value=30)
    def test_defaults(self, _mock_q):
        from retention_policy import get_policy_defaults

        defaults = get_policy_defaults()
        assert defaults["activity_days"] == 2555
        assert defaults["quarantine_days"] == 30
        assert defaults["indexing_runs_days"] == 10950
        assert defaults["saml_sessions"] == "expiry_only"

    @patch.dict(
        "os.environ",
        {
            "ACTIVITY_RETENTION_DAYS": "90",
            "INDEXING_RUNS_RETENTION_DAYS": "14",
        },
        clear=False,
    )
    @patch("quarantine.get_retention_days", return_value=7)
    def test_defaults_from_env(self, _mock_q):
        from retention_policy import get_policy_defaults

        defaults = get_policy_defaults()
        assert defaults["activity_days"] == 90
        assert defaults["quarantine_days"] == 7
        assert defaults["indexing_runs_days"] == 14


class TestApplyRetention:
    @patch("saml_auth.cleanup_expired_sessions", return_value=4)
    @patch("indexing_runs.apply_retention", return_value=3)
    @patch("quarantine.purge_expired", return_value=2)
    @patch("activity_log.apply_retention", return_value=1)
    @patch("quarantine.get_retention_days", return_value=30)
    def test_apply_orchestrates_all(
        self,
        _mock_q_days,
        mock_activity,
        mock_quarantine,
        mock_runs,
        mock_saml,
    ):
        from retention_policy import apply_retention

        result = apply_retention()

        assert result["ok"] is True
        assert result["activity_deleted"] == 1
        assert result["quarantine_purged"] == 2
        assert result["indexing_runs_deleted"] == 3
        assert result["saml_sessions_deleted"] == 4

        mock_activity.assert_called_once_with(2555)
        mock_quarantine.assert_called_once_with(retention_days=30)
        mock_runs.assert_called_once_with(10950)
        mock_saml.assert_called_once()

    @patch("quarantine.get_retention_days", return_value=30)
    @patch("activity_log.apply_retention", side_effect=RuntimeError("boom"))
    def test_apply_handles_failure(self, _mock_activity, _mock_days):
        from retention_policy import apply_retention

        result = apply_retention()
        assert result["ok"] is False
        assert "error" in result

    @patch("saml_auth.cleanup_expired_sessions")
    @patch("indexing_runs.apply_retention", return_value=1)
    @patch("quarantine.purge_expired", return_value=1)
    @patch("activity_log.apply_retention", return_value=1)
    @patch("quarantine.get_retention_days", return_value=30)
    def test_apply_can_skip_saml_cleanup(
        self,
        _mock_days,
        _mock_activity,
        _mock_quarantine,
        _mock_runs,
        mock_saml,
    ):
        from retention_policy import apply_retention

        result = apply_retention(cleanup_saml_sessions=False)
        assert result["ok"] is True
        assert result["saml_sessions_deleted"] == 0
        mock_saml.assert_not_called()
