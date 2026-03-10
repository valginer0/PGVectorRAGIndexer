"""Tests for ServerCapabilities, probe_endpoint(), and Organization tab visibility."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import requests

from desktop_app.utils.api_client import APIClient, CapabilityStatus, ProbeResult
from desktop_app.utils.server_capabilities import ServerCapabilities, _PROBES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    return APIClient(base_url="http://test-server")


@pytest.fixture
def caps(api_client):
    return ServerCapabilities(api_client)


# ---------------------------------------------------------------------------
# probe_endpoint() tests
# ---------------------------------------------------------------------------

class TestProbeEndpoint:
    """Test APIClient.probe_endpoint() status-code mapping."""

    def test_probe_200_returns_available(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"users": []}

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.AVAILABLE
        assert result.body == {"users": []}
        assert result.error_message is None
        assert result.status_code == 200

    def test_probe_401_returns_unauthorized(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.UNAUTHORIZED
        assert result.status_code == 401

    def test_probe_403_returns_unauthorized(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.UNAUTHORIZED
        assert result.status_code == 403

    def test_probe_404_returns_not_supported(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.NOT_SUPPORTED
        assert result.status_code == 404

    def test_probe_405_returns_not_supported(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 405

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.NOT_SUPPORTED

    def test_probe_500_returns_available_with_error(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"detail": "Internal server error"}

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.AVAILABLE
        assert result.error_message == "Internal server error"
        assert result.status_code == 500

    def test_probe_500_non_json_falls_back_to_text(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("not JSON")
        mock_resp.text = "<html>Server Error</html>"

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.AVAILABLE
        assert "Server Error" in result.error_message

    def test_probe_connection_error_returns_unreachable(self, api_client):
        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.side_effect = requests.exceptions.ConnectionError()
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.UNREACHABLE
        assert result.status_code is None

    def test_probe_timeout_returns_unreachable(self, api_client):
        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.side_effect = requests.exceptions.Timeout()
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.UNREACHABLE

    def test_probe_200_non_json_body_is_none(self, api_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not JSON")

        with patch.object(api_client._base, "_session") as mock_session:
            mock_session.request.return_value = mock_resp
            result = api_client.probe_endpoint("/api/v1/users")

        assert result.status == CapabilityStatus.AVAILABLE
        assert result.body is None


# ---------------------------------------------------------------------------
# ServerCapabilities tests
# ---------------------------------------------------------------------------

class TestServerCapabilities:

    def test_initial_state_unknown(self, caps):
        for name in _PROBES:
            assert caps.get(name) == CapabilityStatus.UNKNOWN
        assert not caps.is_available("users")
        assert not caps.is_admin()
        assert caps.get_identity() is None

    def test_probe_all_caches_available(self, caps, api_client):
        def fake_probe(path, timeout=3):
            if "/me" in path:
                return ProbeResult(
                    status=CapabilityStatus.AVAILABLE,
                    body={"user": None, "role": "admin", "permissions": ["system.admin"]},
                    status_code=200,
                )
            return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)

        with patch.object(api_client, "probe_endpoint", side_effect=fake_probe):
            result = caps.probe_all()

        assert all(v == CapabilityStatus.AVAILABLE for v in result.values())
        assert caps.is_available("users")
        assert caps.is_available("roles")
        assert caps.is_admin()

    def test_unreachable_not_cached(self, caps, api_client):
        """UNREACHABLE results should not be stored in the cache."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)):
            caps.probe_all()

        # Cache should still be empty — UNREACHABLE is never cached
        for name in _PROBES:
            assert caps.get(name) == CapabilityStatus.UNKNOWN

    def test_unreachable_preserves_previous_value(self, caps, api_client):
        """If a probe was previously AVAILABLE then goes UNREACHABLE, keep the old value."""
        # First probe: AVAILABLE
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)):
            caps.probe_all()
        assert caps.is_available("users")

        # Second probe: UNREACHABLE
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)):
            caps.probe_all()
        # Should still show previous AVAILABLE
        assert caps.is_available("users")

    def test_unauthorized_cached(self, caps, api_client):
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)):
            caps.probe_all()

        assert caps.get("users") == CapabilityStatus.UNAUTHORIZED
        assert not caps.is_available("users")

    def test_not_supported_cached(self, caps, api_client):
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)):
            caps.probe_all()

        assert caps.get("users") == CapabilityStatus.NOT_SUPPORTED

    def test_any_available_excludes_me(self, caps, api_client):
        """any_available() should not count /me."""
        def fake_probe(path, timeout=3):
            if "/me" in path:
                return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)
            return ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)

        with patch.object(api_client, "probe_endpoint", side_effect=fake_probe):
            caps.probe_all()

        assert not caps.any_available()

    def test_any_unauthorized(self, caps, api_client):
        """any_unauthorized() returns True when probes hit 401/403."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)):
            caps.probe_all()

        assert caps.any_unauthorized()

    def test_any_unauthorized_excludes_me(self, caps, api_client):
        """any_unauthorized() excludes /me."""
        def fake_probe(path, timeout=3):
            if "/me" in path:
                return ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)
            return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)

        with patch.object(api_client, "probe_endpoint", side_effect=fake_probe):
            caps.probe_all()

        assert not caps.any_unauthorized()  # Only /me was unauthorized
        assert caps.any_available()

    def test_is_admin_false_without_me(self, caps):
        assert not caps.is_admin()

    def test_is_admin_false_without_permission(self, caps, api_client):
        def fake_probe(path, timeout=3):
            if "/me" in path:
                return ProbeResult(
                    status=CapabilityStatus.AVAILABLE,
                    body={"role": "user", "permissions": ["docs.read"]},
                    status_code=200,
                )
            return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)

        with patch.object(api_client, "probe_endpoint", side_effect=fake_probe):
            caps.probe_all()

        assert not caps.is_admin()

    def test_invalidate_clears_everything(self, caps, api_client):
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(
                              status=CapabilityStatus.AVAILABLE,
                              body={"permissions": ["system.admin"]},
                              status_code=200)):
            caps.probe_all()

        assert caps.is_available("users")
        assert caps.is_admin()

        caps.invalidate()

        assert not caps.is_available("users")
        assert not caps.is_admin()
        assert caps.get_identity() is None

    def test_probing_guard_prevents_reentrant(self, caps, api_client):
        """If _probing is True, probe_all() returns cached state without re-probing."""
        caps._probing = True
        # Should not call probe_endpoint at all
        with patch.object(api_client, "probe_endpoint") as mock_probe:
            caps.probe_all()
            mock_probe.assert_not_called()

    def test_all_unreachable_or_unknown_true_when_empty(self, caps):
        assert caps.all_unreachable_or_unknown()

    def test_all_unreachable_or_unknown_false_when_cached(self, caps, api_client):
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)):
            caps.probe_all()
        assert not caps.all_unreachable_or_unknown()

    def test_get_error(self, caps, api_client):
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(
                              status=CapabilityStatus.AVAILABLE,
                              error_message="DB connection pool exhausted",
                              status_code=500)):
            caps.probe_all()
        assert caps.get_error("users") == "DB connection pool exhausted"


# ---------------------------------------------------------------------------
# Visibility logic tests
# ---------------------------------------------------------------------------

class TestVisibilityLogic:
    """Test the state-machine in OrganizationTab._update_visibility().

    We test the logic indirectly by verifying the conditions that
    _update_visibility checks, since the actual method requires Qt widgets.
    """

    def test_all_unauthorized_detected(self, caps, api_client):
        """When all probes return UNAUTHORIZED, any_unauthorized() is True
        and any_available() is False — triggers auth message, not gated/not-supported."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)):
            caps.probe_all()

        has_any = caps.any_available()
        has_auth_issue = caps.any_unauthorized()
        all_unreachable = caps.all_unreachable_or_unknown()

        assert not has_any
        assert has_auth_issue
        assert not all_unreachable
        # This is the bug-fix scenario: auth issue should be checked BEFORE
        # falling through to "not supported" or gated logic

    def test_mixed_available_and_not_supported(self, caps, api_client):
        """Some endpoints available, some not supported — shows available panels."""
        def fake_probe(path, timeout=3):
            if "/users" in path or "/me" in path:
                return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)
            return ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)

        with patch.object(api_client, "probe_endpoint", side_effect=fake_probe):
            caps.probe_all()

        assert caps.any_available()
        assert caps.is_available("users")
        assert not caps.is_available("retention")

    def test_all_unreachable_state(self, caps, api_client):
        """When all probes fail with connection error, all_unreachable_or_unknown is True."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)):
            caps.probe_all()

        assert not caps.any_available()
        assert not caps.any_unauthorized()
        assert caps.all_unreachable_or_unknown()

    def test_community_with_available_server(self, caps, api_client):
        """Community edition + server with org endpoints = should show panels."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)):
            caps.probe_all()

        # any_available True → show tabs regardless of local license
        assert caps.any_available()
