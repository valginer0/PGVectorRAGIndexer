"""
Phase D Verification Tests — Desktop API Client Facade

Automated equivalents of the manual QA checklist in docs/PHASE_D_VERIFICATION.md.
Covers: property synchronization, error translation, session lifecycle,
error detail preservation, and domain client routing completeness.
"""

import pytest
import requests
from unittest.mock import MagicMock, patch

from desktop_app.utils.api_client import APIClient
from desktop_app.utils.api_client_core.base_client import BaseAPIClient
from desktop_app.utils.errors import (
    APIError, APIConnectionError, APIAuthenticationError, APIRateLimitError
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_client():
    return BaseAPIClient(base_url="http://test-server:8000", api_key="pgv_sk_test123")


@pytest.fixture
def api_client():
    return APIClient(base_url="http://test-server:8000", api_key="pgv_sk_test123")


# ---------------------------------------------------------------------------
# Scenario 7: Property Synchronization
# ---------------------------------------------------------------------------

class TestPropertySynchronization:
    """Verify base_url, api_base, and api_key propagate correctly."""

    def test_base_url_derives_api_base(self, base_client):
        """Setting base_url auto-derives api_base to {base_url}/api/v1."""
        assert base_client.base_url == "http://test-server:8000"
        assert base_client.api_base == "http://test-server:8000/api/v1"

    def test_base_url_change_updates_api_base(self, base_client):
        """Changing base_url re-derives api_base."""
        base_client.base_url = "http://other-host:9000"
        assert base_client.api_base == "http://other-host:9000/api/v1"

    def test_base_url_strips_trailing_slash(self, base_client):
        """Trailing slashes are normalized away."""
        base_client.base_url = "http://host:8000/"
        assert base_client.base_url == "http://host:8000"
        assert base_client.api_base == "http://host:8000/api/v1"

    def test_api_key_sets_session_header(self, base_client):
        """Setting api_key immediately updates the session X-API-Key header."""
        assert base_client._session.headers.get("X-API-Key") == "pgv_sk_test123"

    def test_api_key_change_updates_header(self, base_client):
        """Changing api_key updates the header for subsequent requests."""
        base_client.api_key = "pgv_sk_new_key"
        assert base_client._session.headers["X-API-Key"] == "pgv_sk_new_key"

    def test_api_key_none_removes_header(self, base_client):
        """Setting api_key to None removes the header."""
        base_client.api_key = None
        assert "X-API-Key" not in base_client._session.headers

    def test_facade_propagates_base_url_to_base(self, api_client):
        """APIClient facade property changes reach BaseAPIClient."""
        api_client.base_url = "http://changed:5000"
        assert api_client._base.base_url == "http://changed:5000"
        assert api_client._base.api_base == "http://changed:5000/api/v1"

    def test_facade_propagates_api_key_to_base(self, api_client):
        """APIClient facade _api_key changes reach BaseAPIClient session."""
        api_client._api_key = "pgv_sk_facade_key"
        assert api_client._base._session.headers["X-API-Key"] == "pgv_sk_facade_key"

    def test_api_base_manual_override(self, base_client):
        """Direct api_base setter works for legacy compatibility."""
        base_client.api_base = "http://custom-base/v2/"
        assert base_client.api_base == "http://custom-base/v2"  # trailing slash stripped


# ---------------------------------------------------------------------------
# Scenario 6: Error Translation
# ---------------------------------------------------------------------------

class TestErrorTranslation:
    """Verify HTTP status codes map to typed exceptions."""

    def _mock_response(self, status_code, json_body=None, text=""):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.text = text
        if json_body is not None:
            resp.json.return_value = json_body
        else:
            resp.json.side_effect = ValueError("No JSON")
        return resp

    def test_401_raises_auth_error(self, base_client):
        """HTTP 401 → APIAuthenticationError."""
        resp = self._mock_response(401, {"detail": "Invalid API key"})
        with pytest.raises(APIAuthenticationError, match="Invalid API key") as exc_info:
            base_client._handle_response_errors(resp)
        assert exc_info.value.status_code == 401

    def test_403_raises_auth_error(self, base_client):
        """HTTP 403 → APIAuthenticationError."""
        resp = self._mock_response(403, {"detail": "Forbidden"})
        with pytest.raises(APIAuthenticationError) as exc_info:
            base_client._handle_response_errors(resp)
        assert exc_info.value.status_code == 403

    def test_429_raises_rate_limit_error(self, base_client):
        """HTTP 429 → APIRateLimitError."""
        resp = self._mock_response(429, {"detail": "Too many requests"})
        with pytest.raises(APIRateLimitError, match="Too many requests") as exc_info:
            base_client._handle_response_errors(resp)
        assert exc_info.value.status_code == 429

    def test_404_raises_api_error(self, base_client):
        """HTTP 404 → generic APIError with status_code."""
        resp = self._mock_response(404, {"detail": "Not found"})
        with pytest.raises(APIError) as exc_info:
            base_client._handle_response_errors(resp)
        assert exc_info.value.status_code == 404
        assert not isinstance(exc_info.value, APIAuthenticationError)

    def test_500_raises_api_error(self, base_client):
        """HTTP 500 → generic APIError."""
        resp = self._mock_response(500, {"detail": "Internal error"})
        with pytest.raises(APIError) as exc_info:
            base_client._handle_response_errors(resp)
        assert exc_info.value.status_code == 500

    def test_200_does_not_raise(self, base_client):
        """HTTP 200 passes through without exception."""
        resp = self._mock_response(200)
        base_client._handle_response_errors(resp)  # Should not raise

    def test_error_detail_preserved_from_json(self, base_client):
        """Error message comes from response JSON 'detail' field, not generic."""
        resp = self._mock_response(422, {"detail": "Validation: field X is required"})
        with pytest.raises(APIError, match="Validation: field X is required"):
            base_client._handle_response_errors(resp)

    def test_error_fallback_to_text(self, base_client):
        """When response has no JSON, falls back to response text."""
        resp = self._mock_response(502, text="Bad Gateway")
        with pytest.raises(APIError, match="Bad Gateway"):
            base_client._handle_response_errors(resp)

    def test_connection_error_translated(self, base_client):
        """requests.ConnectionError → APIConnectionError."""
        with patch.object(base_client._session, "request",
                          side_effect=requests.exceptions.ConnectionError("refused")):
            with pytest.raises(APIConnectionError, match="Failed to connect"):
                base_client.request("GET", "http://test/health")

    def test_timeout_error_translated(self, base_client):
        """requests.Timeout → APIConnectionError."""
        with patch.object(base_client._session, "request",
                          side_effect=requests.exceptions.Timeout("timed out")):
            with pytest.raises(APIConnectionError, match="timed out"):
                base_client.request("GET", "http://test/health")

    def test_generic_request_error_translated(self, base_client):
        """Other requests.RequestException → APIError."""
        with patch.object(base_client._session, "request",
                          side_effect=requests.exceptions.RequestException("unknown")):
            with pytest.raises(APIError, match="API request failed"):
                base_client.request("GET", "http://test/health")


# ---------------------------------------------------------------------------
# Scenario 8: Session Lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    """Verify session management and cleanup."""

    def test_close_closes_session(self, base_client):
        """close() calls session.close()."""
        with patch.object(base_client._session, "close") as mock_close:
            base_client.close()
            mock_close.assert_called_once()

    def test_shared_session_across_requests(self, base_client):
        """Multiple requests reuse the same session instance."""
        session_id = id(base_client._session)
        # Simulate two requests
        with patch.object(base_client._session, "request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_req.return_value = mock_resp

            base_client.request("GET", "http://test/a")
            base_client.request("GET", "http://test/b")

            assert id(base_client._session) == session_id
            assert mock_req.call_count == 2

    def test_timeout_default_applied(self, base_client):
        """Default timeout is applied to requests when not overridden."""
        with patch.object(base_client._session, "request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_req.return_value = mock_resp

            base_client.request("GET", "http://test/health")
            _, kwargs = mock_req.call_args
            assert kwargs["timeout"] == 7200  # default from __init__


# ---------------------------------------------------------------------------
# Domain Client Routing Completeness
# ---------------------------------------------------------------------------

class TestDomainClientRouting:
    """Verify facade routes to correct domain clients (spot checks beyond existing tests)."""

    def test_all_nine_domain_clients_instantiated(self, api_client):
        """APIClient creates all 9 domain clients."""
        assert hasattr(api_client, '_system')
        assert hasattr(api_client, '_document')
        assert hasattr(api_client, '_search')
        assert hasattr(api_client, '_metadata')
        assert hasattr(api_client, '_indexing')
        assert hasattr(api_client, '_user')
        assert hasattr(api_client, '_activity')
        assert hasattr(api_client, '_watched_folders')
        assert hasattr(api_client, '_identity')

    def test_domain_clients_share_base(self, api_client):
        """All domain clients reference the same BaseAPIClient instance."""
        base = api_client._base
        assert api_client._system._base is base
        assert api_client._document._base is base
        assert api_client._search._base is base
        assert api_client._metadata._base is base
        assert api_client._indexing._base is base
        assert api_client._user._base is base
        assert api_client._activity._base is base
        assert api_client._watched_folders._base is base
        assert api_client._identity._base is base


# ---------------------------------------------------------------------------
# Error Hierarchy
# ---------------------------------------------------------------------------

class TestErrorHierarchy:
    """Verify exception class hierarchy."""

    def test_connection_error_is_api_error(self):
        """APIConnectionError inherits from APIError."""
        assert issubclass(APIConnectionError, APIError)

    def test_auth_error_is_api_error(self):
        """APIAuthenticationError inherits from APIError."""
        assert issubclass(APIAuthenticationError, APIError)

    def test_rate_limit_error_is_api_error(self):
        """APIRateLimitError inherits from APIError."""
        assert issubclass(APIRateLimitError, APIError)

    def test_api_error_has_status_code(self):
        """APIError carries optional status_code."""
        err = APIError("test", status_code=418)
        assert err.status_code == 418
        assert str(err) == "test"
