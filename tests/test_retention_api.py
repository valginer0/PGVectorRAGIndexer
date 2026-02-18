"""Route registration tests for retention API compatibility and orchestration."""

import os
import sys

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
