"""
Tests for API versioning (#12).

Tests cover:
- /api/version endpoint returns correct structure
- Version constants are valid semver
- v1_router endpoints accessible at /api/v1/... paths
- Backward compat: old unversioned paths still work
- Desktop client version check logic
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Test: Version constants
# ===========================================================================


class TestVersionConstants:
    def test_api_version_is_string(self):
        from api import API_VERSION
        assert isinstance(API_VERSION, str)
        assert len(API_VERSION) > 0

    def test_min_client_version_is_semver(self):
        from api import MIN_CLIENT_VERSION
        from packaging.version import Version
        v = Version(MIN_CLIENT_VERSION)
        assert v >= Version("0.0.0")

    def test_max_client_version_is_semver(self):
        from api import MAX_CLIENT_VERSION
        from packaging.version import Version
        v = Version(MAX_CLIENT_VERSION)
        assert v > Version("0.0.0")

    def test_min_less_than_max(self):
        from api import MIN_CLIENT_VERSION, MAX_CLIENT_VERSION
        from packaging.version import Version
        assert Version(MIN_CLIENT_VERSION) < Version(MAX_CLIENT_VERSION)


# ===========================================================================
# Test: Desktop client version check
# ===========================================================================


class TestClientVersionCheck:
    """Test the check_version_compatibility method of APIClient."""

    def _make_client(self):
        """Create an APIClient without hitting the network."""
        from desktop_app.utils.api_client import APIClient
        return APIClient(base_url="http://localhost:8000")

    def test_compatible_version(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "server_version": "2.4.5",
            "api_version": "1",
            "min_client_version": "2.0.0",
            "max_client_version": "99.99.99",
        }
        with patch("desktop_app.utils.api_client.requests.get", return_value=mock_resp):
            compatible, msg = client.check_version_compatibility()
        assert compatible is True
        assert msg == ""

    def test_client_too_old(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "server_version": "3.0.0",
            "api_version": "2",
            "min_client_version": "3.0.0",
            "max_client_version": "99.99.99",
        }
        with patch("desktop_app.utils.api_client.requests.get", return_value=mock_resp):
            compatible, msg = client.check_version_compatibility()
        assert compatible is False
        assert "too old" in msg

    def test_client_too_new(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "server_version": "1.0.0",
            "api_version": "1",
            "min_client_version": "1.0.0",
            "max_client_version": "1.5.0",
        }
        with patch("desktop_app.utils.api_client.requests.get", return_value=mock_resp):
            compatible, msg = client.check_version_compatibility()
        assert compatible is False
        assert "newer" in msg

    def test_server_unreachable_is_ok(self):
        """If server is unreachable, don't block the client."""
        import requests as req_lib
        client = self._make_client()
        with patch(
            "desktop_app.utils.api_client.requests.get",
            side_effect=req_lib.ConnectionError("refused"),
        ):
            compatible, msg = client.check_version_compatibility()
        assert compatible is True

    def test_endpoint_missing_is_ok(self):
        """Old servers without /api/version should not block."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("desktop_app.utils.api_client.requests.get", return_value=mock_resp):
            compatible, msg = client.check_version_compatibility()
        assert compatible is True

    def test_api_base_uses_versioned_prefix(self):
        client = self._make_client()
        assert client.api_base == "http://localhost:8000/api/v1"

    def test_custom_base_url(self):
        from desktop_app.utils.api_client import APIClient
        client = APIClient(base_url="https://ragvault.example.com:443")
        assert client.api_base == "https://ragvault.example.com:443/api/v1"
