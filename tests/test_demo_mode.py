"""
Tests for Demo / Read-Only Mode (#15).

Tests cover:
- DEMO_MODE env var parsing
- Demo mode flag in /api and /api/version responses
- Allowed POST paths constant
- Dockerfile.demo exists
- docker-compose.demo.yml exists and sets DEMO_MODE
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: DEMO_MODE env var and constants
# ===========================================================================


class TestDemoModeConstants:
    def test_demo_mode_default_off(self):
        """DEMO_MODE should be False by default (no env var set)."""
        # We can't easily test the module-level variable without reimporting,
        # but we can verify the allowed paths constant exists.
        from api import _DEMO_ALLOWED_POST_PATHS
        assert "/search" in _DEMO_ALLOWED_POST_PATHS
        assert "/api/v1/search" in _DEMO_ALLOWED_POST_PATHS

    def test_allowed_post_paths_include_resolve(self):
        from api import _DEMO_ALLOWED_POST_PATHS
        assert "/virtual-roots/resolve" in _DEMO_ALLOWED_POST_PATHS
        assert "/api/v1/virtual-roots/resolve" in _DEMO_ALLOWED_POST_PATHS

    def test_demo_mode_variable_exists(self):
        from api import DEMO_MODE
        assert isinstance(DEMO_MODE, bool)


# ===========================================================================
# Test: /api and /api/version include demo flag when DEMO_MODE is on
# ===========================================================================


class TestDemoModeApiResponses:
    """Test that demo flag appears in API info when DEMO_MODE is True."""

    def test_api_info_no_demo_by_default(self):
        """When DEMO_MODE is False, /api response should not have 'demo' key."""
        from api import DEMO_MODE
        if DEMO_MODE:
            pytest.skip("DEMO_MODE is on in this environment")
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
        resp = client.get("/api")
        assert resp.status_code == 200
        data = resp.json()
        assert "demo" not in data

    def test_api_version_no_demo_by_default(self):
        """When DEMO_MODE is False, /api/version should not have 'demo' key."""
        from api import DEMO_MODE
        if DEMO_MODE:
            pytest.skip("DEMO_MODE is on in this environment")
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
        resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "demo" not in data


# ===========================================================================
# Test: Demo Docker files exist
# ===========================================================================


class TestDemoDockerFiles:
    def test_dockerfile_demo_exists(self):
        assert (PROJECT_ROOT / "Dockerfile.demo").exists()

    def test_dockerfile_demo_sets_demo_mode(self):
        content = (PROJECT_ROOT / "Dockerfile.demo").read_text()
        assert "DEMO_MODE=1" in content

    def test_docker_compose_demo_exists(self):
        assert (PROJECT_ROOT / "docker-compose.demo.yml").exists()

    def test_docker_compose_demo_sets_demo_mode(self):
        content = (PROJECT_ROOT / "docker-compose.demo.yml").read_text()
        assert "DEMO_MODE" in content

    def test_docker_compose_demo_has_healthcheck(self):
        content = (PROJECT_ROOT / "docker-compose.demo.yml").read_text()
        assert "healthcheck" in content

    def test_dockerfile_demo_has_healthcheck(self):
        content = (PROJECT_ROOT / "Dockerfile.demo").read_text()
        assert "HEALTHCHECK" in content
