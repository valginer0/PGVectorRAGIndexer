"""Tests for compliance_export module and API endpoint."""

import io
import json
import os
import sys
import zipfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Unit tests for export_compliance_report()
# ---------------------------------------------------------------------------


class TestExportComplianceReport:
    """Test the ZIP generation function."""

    @patch("quarantine.get_quarantine_stats", return_value={"total_documents": 3})
    @patch("indexing_runs.get_recent_runs", return_value=[{"id": "r1", "status": "success"}])
    @patch("activity_log.export_csv", return_value="id,ts\n1,2026-01-01\n")
    @patch("users.list_users", return_value=[
        {"id": "u1", "email": "a@b.com", "display_name": "A", "role": "admin", "created_at": "2026-01-01", "is_active": True},
    ])
    @patch("retention_policy.get_policy_defaults", return_value={"activity_days": 2555, "quarantine_days": 30})
    def test_export_returns_valid_zip(self, *mocks):
        from compliance_export import export_compliance_report
        data = export_compliance_report()
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert zf.testzip() is None  # No corrupt entries

    @patch("quarantine.get_quarantine_stats", return_value={})
    @patch("indexing_runs.get_recent_runs", return_value=[])
    @patch("activity_log.export_csv", return_value="")
    @patch("users.list_users", return_value=[])
    @patch("retention_policy.get_policy_defaults", return_value={})
    def test_export_contains_expected_files(self, *mocks):
        from compliance_export import export_compliance_report
        data = export_compliance_report()
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        assert "metadata.json" in names
        assert "retention_policy.json" in names
        assert "users.csv" in names
        assert "activity_log.csv" in names
        assert "indexing_summary.json" in names
        assert "quarantine_summary.json" in names

    @patch("quarantine.get_quarantine_stats", return_value={})
    @patch("indexing_runs.get_recent_runs", return_value=[])
    @patch("activity_log.export_csv", return_value="")
    @patch("users.list_users", return_value=[])
    @patch("retention_policy.get_policy_defaults", return_value={})
    def test_export_metadata_has_version(self, *mocks):
        from compliance_export import export_compliance_report
        data = export_compliance_report()
        zf = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(zf.read("metadata.json"))
        assert "server_version" in meta
        assert "exported_at" in meta

    @patch("quarantine.get_quarantine_stats", return_value={})
    @patch("indexing_runs.get_recent_runs", return_value=[])
    @patch("activity_log.export_csv", return_value="")
    @patch("users.list_users", side_effect=Exception("no users table"))
    @patch("retention_policy.get_policy_defaults", return_value={})
    def test_export_resilient_to_missing_users(self, *mocks):
        """If users module fails, the rest of the report should still generate."""
        from compliance_export import export_compliance_report
        data = export_compliance_report()
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        # users.csv should be absent but everything else present
        assert "users.csv" not in names
        assert "metadata.json" in names
        assert "retention_policy.json" in names
        # metadata should record the error
        meta = json.loads(zf.read("metadata.json"))
        assert len(meta["errors"]) > 0
        assert "users" in meta["errors"][0]


# ---------------------------------------------------------------------------
# API endpoint registration tests
# ---------------------------------------------------------------------------


class TestComplianceEndpoint:
    @pytest.fixture(autouse=True)
    def _load_routes(self):
        from api import v1_router
        self.routes = {r.path: r for r in v1_router.routes}

    def test_compliance_endpoint_registered(self):
        assert "/compliance/export" in self.routes

    def test_compliance_endpoint_requires_admin(self):
        route = self.routes["/compliance/export"]
        dep_names = [d.dependency.__name__ for d in route.dependencies]
        assert "require_admin" in dep_names
