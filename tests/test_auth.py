"""
Unit tests for API key authentication module.

Tests key generation, hashing, verification, and the FastAPI
auth dependency behavior.
"""

import hashlib
import os
import re
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import HTTPException

from auth import (
    KEY_PREFIX,
    KEY_RANDOM_BYTES,
    GRACE_PERIOD_HOURS,
    generate_api_key,
    hash_api_key,
    verify_api_key,
    get_key_prefix,
    is_loopback_request,
    is_auth_required,
    require_api_key,
)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    def test_prefix(self):
        key, _ = generate_api_key()
        assert key.startswith(KEY_PREFIX)

    def test_length(self):
        key, _ = generate_api_key()
        # pgv_sk_ (7 chars) + 64 hex chars (32 bytes) = 71
        assert len(key) == 7 + KEY_RANDOM_BYTES * 2

    def test_unique(self):
        keys = {generate_api_key()[0] for _ in range(20)}
        assert len(keys) == 20, "Keys should be unique"

    def test_returns_hash(self):
        key, key_hash = generate_api_key()
        assert key_hash == hash_api_key(key)

    def test_hex_chars_only(self):
        key, _ = generate_api_key()
        random_part = key[len(KEY_PREFIX):]
        assert re.match(r'^[0-9a-f]+$', random_part)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


class TestHashing:
    def test_sha256(self):
        key = "pgv_sk_abc123"
        expected = hashlib.sha256(key.encode("utf-8")).hexdigest()
        assert hash_api_key(key) == expected

    def test_deterministic(self):
        key = "pgv_sk_test_key"
        assert hash_api_key(key) == hash_api_key(key)

    def test_different_keys_different_hashes(self):
        h1 = hash_api_key("pgv_sk_key1")
        h2 = hash_api_key("pgv_sk_key2")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class TestVerification:
    def test_correct_key(self):
        key, key_hash = generate_api_key()
        assert verify_api_key(key, key_hash) is True

    def test_wrong_key(self):
        _, key_hash = generate_api_key()
        assert verify_api_key("pgv_sk_wrong", key_hash) is False

    def test_empty_key(self):
        _, key_hash = generate_api_key()
        assert verify_api_key("", key_hash) is False

    def test_hash_of_different_key(self):
        key1, _ = generate_api_key()
        _, hash2 = generate_api_key()
        assert verify_api_key(key1, hash2) is False


# ---------------------------------------------------------------------------
# Key prefix extraction
# ---------------------------------------------------------------------------


class TestKeyPrefix:
    def test_normal_key(self):
        key = "pgv_sk_a1b2c3d4e5f6"
        assert get_key_prefix(key) == "pgv_sk_a1b2c"

    def test_short_string(self):
        assert get_key_prefix("abc") == "abc"

    def test_exact_12(self):
        assert get_key_prefix("pgv_sk_12345") == "pgv_sk_12345"


# ---------------------------------------------------------------------------
# Loopback detection
# ---------------------------------------------------------------------------


class TestLoopbackDetection:
    def _make_request(self, host):
        """Create a mock request with the given client host."""
        request = MagicMock()
        client = MagicMock()
        client.host = host
        request.client = client
        return request

    def test_ipv4_loopback(self):
        assert is_loopback_request(self._make_request("127.0.0.1")) is True

    def test_ipv6_loopback(self):
        assert is_loopback_request(self._make_request("::1")) is True

    def test_localhost_string(self):
        assert is_loopback_request(self._make_request("localhost")) is True

    def test_remote_ip(self):
        assert is_loopback_request(self._make_request("192.168.1.100")) is False

    def test_public_ip(self):
        assert is_loopback_request(self._make_request("8.8.8.8")) is False

    def test_no_client(self):
        request = MagicMock()
        request.client = None
        assert is_loopback_request(request) is False


# ---------------------------------------------------------------------------
# Auth required logic
# ---------------------------------------------------------------------------


class TestAuthRequired:
    def _make_request(self, host="127.0.0.1"):
        request = MagicMock()
        client = MagicMock()
        client.host = host
        request.client = client
        return request

    @patch("config.get_config")
    def test_auth_disabled(self, mock_config):
        mock_config.return_value.api.require_auth = False
        request = self._make_request()
        assert is_auth_required(request) is False

    @patch("config.get_config")
    def test_auth_enabled_remote(self, mock_config):
        mock_config.return_value.api.require_auth = True
        request = self._make_request(host="192.168.1.100")
        assert is_auth_required(request) is True

    @patch.dict(os.environ, {}, clear=False)
    @patch("config.get_config")
    def test_auth_enabled_loopback_exempt(self, mock_config):
        # Ensure FORCE_ALL is not interfering
        if "API_AUTH_FORCE_ALL" in os.environ:
            del os.environ["API_AUTH_FORCE_ALL"]
        mock_config.return_value.api.require_auth = True
        request = self._make_request(host="127.0.0.1")
        assert is_auth_required(request) is False

    @patch.dict(os.environ, {}, clear=False)
    @patch("config.get_config")
    def test_auth_enabled_ipv6_loopback_exempt(self, mock_config):
        # Ensure FORCE_ALL is not interfering
        if "API_AUTH_FORCE_ALL" in os.environ:
            del os.environ["API_AUTH_FORCE_ALL"]
        mock_config.return_value.api.require_auth = True
        request = self._make_request(host="::1")
        assert is_auth_required(request) is False

    @patch.dict(os.environ, {"API_REQUIRE_AUTH": "true"}, clear=False)
    @patch("config.get_config")
    def test_loopback_exempt_by_default(self, mock_config):
        """Without API_AUTH_FORCE_ALL, loopback requests are exempt."""
        mock_config.return_value.api.require_auth = True
        # Ensure FORCE_ALL is not set
        os.environ.pop("API_AUTH_FORCE_ALL", None)
        request = self._make_request(host="127.0.0.1")
        assert is_auth_required(request) is False

    @patch.dict(os.environ, {"API_AUTH_FORCE_ALL": "true"}, clear=False)
    @patch("config.get_config")
    def test_force_all_overrides_loopback(self, mock_config):
        """API_AUTH_FORCE_ALL=true disables loopback exemption."""
        mock_config.return_value.api.require_auth = True
        request = self._make_request(host="127.0.0.1")
        assert is_auth_required(request) is True


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


class TestRequireApiKey:
    """Tests for the require_api_key FastAPI dependency."""

    def _make_request(self, host="127.0.0.1"):
        request = MagicMock()
        client = MagicMock()
        client.host = host
        request.client = client
        return request

    @pytest.mark.asyncio
    @patch("auth.is_auth_required", return_value=False)
    async def test_auth_not_required_no_key(self, mock_auth):
        """When auth is not required, allow through without key."""
        request = self._make_request()
        result = await require_api_key(request, None)
        assert result is None

    @pytest.mark.asyncio
    @patch("auth.is_auth_required", return_value=True)
    async def test_auth_required_no_key_401(self, mock_auth):
        """When auth is required and no key provided, raise 401."""
        request = self._make_request("192.168.1.1")
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, None)
        assert exc_info.value.status_code == 401
        assert "API key required" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    @patch("auth.is_auth_required", return_value=True)
    async def test_auth_required_bad_prefix_401(self, mock_auth):
        """When auth is required and key has wrong prefix, raise 401."""
        request = self._make_request("192.168.1.1")
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, "bad_key_no_prefix")
        assert exc_info.value.status_code == 401
        assert "Invalid API key format" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    @patch("auth.update_last_used")
    @patch("auth.lookup_api_key")
    @patch("auth.is_auth_required", return_value=True)
    async def test_auth_required_valid_key(self, mock_auth, mock_lookup, mock_update):
        """When auth is required and key is valid, return key record."""
        key, key_hash = generate_api_key()
        mock_lookup.return_value = {"id": 1, "name": "test"}
        request = self._make_request("192.168.1.1")

        result = await require_api_key(request, key)
        assert result["id"] == 1
        assert result["name"] == "test"
        mock_update.assert_called_once_with(1)

    @pytest.mark.asyncio
    @patch("auth.lookup_api_key", return_value=None)
    @patch("auth.is_auth_required", return_value=True)
    async def test_auth_required_invalid_key_401(self, mock_auth, mock_lookup):
        """When auth is required and key not in database, raise 401."""
        key, _ = generate_api_key()
        request = self._make_request("192.168.1.1")
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, key)
        assert exc_info.value.status_code == 401
        assert "Invalid or revoked" in exc_info.value.detail["message"]

    @pytest.mark.asyncio
    @patch("auth.is_auth_required", return_value=False)
    async def test_auth_not_required_with_key_passes(self, mock_auth):
        """When auth is not required, bypass even if key is provided."""
        key, _ = generate_api_key()
        request = self._make_request()
        result = await require_api_key(request, key)
        assert result is None


# ---------------------------------------------------------------------------
# Desktop APIClient headers
# ---------------------------------------------------------------------------


class TestAPIClientHeaders:
    """Tests for the desktop APIClient header injection."""

    def test_no_api_key(self):
        from desktop_app.utils.api_client import APIClient
        client = APIClient()
        assert client._headers == {}

    def test_with_api_key(self):
        from desktop_app.utils.api_client import APIClient
        client = APIClient(api_key="pgv_sk_test123")
        assert client._headers == {"X-API-Key": "pgv_sk_test123"}

    def test_backward_compatible(self):
        from desktop_app.utils.api_client import APIClient
        # Old init style still works
        client = APIClient("http://localhost:9000")
        assert client.base_url == "http://localhost:9000"
        assert client._headers == {}
