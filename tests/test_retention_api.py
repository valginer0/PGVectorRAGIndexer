"""Route registration tests for retention API compatibility and orchestration."""

import os
import sys
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRetentionEndpoints:
    @pytest.fixture(autouse=True)
    def _load_routes(self):
        from api import v1_router

        self.routes = {r.path for r in v1_router.routes}

    def test_new_retention_endpoints_registered(self):
        assert "/retention/policy" in self.routes
        assert "/retention/run" in self.routes
        assert "/retention/status" in self.routes

    def test_legacy_retention_endpoints_preserved(self):
        assert "/activity/retention" in self.routes
        assert "/quarantine/purge" in self.routes


class TestDeprecationHeaders:
    """Verify legacy endpoints are marked deprecated with RFC 8594 headers."""

    def test_activity_retention_marked_deprecated(self):
        from api import apply_activity_retention
        assert "deprecated" in apply_activity_retention.__doc__.lower()

    def test_quarantine_purge_marked_deprecated(self):
        from api import purge_quarantine
        assert "deprecated" in purge_quarantine.__doc__.lower()

    def test_activity_retention_has_response_param(self):
        import inspect
        from api import apply_activity_retention
        sig = inspect.signature(apply_activity_retention)
        assert "response" in sig.parameters

    def test_quarantine_purge_has_response_param(self):
        import inspect
        from api import purge_quarantine
        sig = inspect.signature(purge_quarantine)
        assert "response" in sig.parameters


class TestDeprecationResponseHeaders:
    """Verify legacy endpoints return RFC 8594 deprecation headers via HTTP."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient
        from api import app
        from auth import require_api_key

        # Bypass auth for test requests
        app.dependency_overrides[require_api_key] = lambda: None
        self.client = TestClient(app, raise_server_exceptions=False)
        yield
        app.dependency_overrides.clear()

    @patch("retention_policy.apply_retention", return_value={
        "ok": True, "activity_deleted": 0, "quarantine_purged": 0,
        "indexing_runs_deleted": 0, "saml_sessions_deleted": 0,
    })
    def test_activity_retention_headers(self, _mock):
        resp = self.client.post("/api/v1/activity/retention", json={"days": 90})
        assert resp.headers.get("Deprecation") == "true"
        assert "2026" in resp.headers.get("Sunset", "")
        assert "successor-version" in resp.headers.get("Link", "")

    @patch("retention_policy.apply_retention", return_value={
        "ok": True, "activity_deleted": 0, "quarantine_purged": 0,
        "indexing_runs_deleted": 0, "saml_sessions_deleted": 0,
    })
    def test_quarantine_purge_headers(self, _mock):
        resp = self.client.post("/api/v1/quarantine/purge")
        assert resp.headers.get("Deprecation") == "true"
        assert "2026" in resp.headers.get("Sunset", "")
        assert "successor-version" in resp.headers.get("Link", "")
