"""
Tests for desktop app configuration and remote backend support (#1).

Tests cover:
- app_config module: get/set/delete, backend mode helpers
- Backend mode defaults and persistence
- API client initialization with saved config
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_app.utils.app_config import (
    get, set, delete,
    get_backend_mode, set_backend_mode,
    get_backend_url, set_backend_url,
    get_api_key, set_api_key,
    is_remote_mode,
    BACKEND_MODE_LOCAL, BACKEND_MODE_REMOTE, DEFAULT_LOCAL_URL,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Use a temp directory for config storage."""
    monkeypatch.setattr(
        "desktop_app.utils.app_config._get_config_dir",
        lambda: tmp_path,
    )
    return tmp_path


# ===========================================================================
# Test: basic get/set/delete
# ===========================================================================


class TestBasicConfig:
    def test_get_missing_returns_default(self, config_dir):
        assert get("nonexistent") is None
        assert get("nonexistent", "fallback") == "fallback"

    def test_set_and_get(self, config_dir):
        set("test_key", "test_value")
        assert get("test_key") == "test_value"

    def test_set_overwrites(self, config_dir):
        set("key", "v1")
        set("key", "v2")
        assert get("key") == "v2"

    def test_delete_removes_key(self, config_dir):
        set("key", "value")
        delete("key")
        assert get("key") is None

    def test_delete_nonexistent_no_error(self, config_dir):
        delete("nonexistent")  # Should not raise

    def test_persists_to_json_file(self, config_dir):
        set("persist_test", 42)
        path = config_dir / "settings.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["persist_test"] == 42


# ===========================================================================
# Test: backend mode helpers
# ===========================================================================


class TestBackendMode:
    def test_default_is_local(self, config_dir):
        assert get_backend_mode() == BACKEND_MODE_LOCAL

    def test_set_remote(self, config_dir):
        set_backend_mode(BACKEND_MODE_REMOTE)
        assert get_backend_mode() == BACKEND_MODE_REMOTE

    def test_set_local(self, config_dir):
        set_backend_mode(BACKEND_MODE_REMOTE)
        set_backend_mode(BACKEND_MODE_LOCAL)
        assert get_backend_mode() == BACKEND_MODE_LOCAL

    def test_is_remote_mode_false_by_default(self, config_dir):
        assert is_remote_mode() is False

    def test_is_remote_mode_true_when_remote(self, config_dir):
        set_backend_mode(BACKEND_MODE_REMOTE)
        assert is_remote_mode() is True


class TestBackendUrl:
    def test_default_url_in_local_mode(self, config_dir):
        assert get_backend_url() == DEFAULT_LOCAL_URL

    def test_custom_url_in_remote_mode(self, config_dir):
        set_backend_mode(BACKEND_MODE_REMOTE)
        set_backend_url("https://my-server.example.com:8000")
        assert get_backend_url() == "https://my-server.example.com:8000"

    def test_local_mode_ignores_saved_url(self, config_dir):
        set_backend_url("https://remote.example.com")
        set_backend_mode(BACKEND_MODE_LOCAL)
        assert get_backend_url() == DEFAULT_LOCAL_URL


class TestApiKey:
    def test_default_is_none(self, config_dir):
        assert get_api_key() is None

    def test_set_and_get(self, config_dir):
        set_api_key("pgv_abc123")
        assert get_api_key() == "pgv_abc123"

    def test_clear_api_key(self, config_dir):
        set_api_key("pgv_abc123")
        set_api_key(None)
        assert get_api_key() is None


# ===========================================================================
# Test: constants
# ===========================================================================


class TestConstants:
    def test_mode_values(self):
        assert BACKEND_MODE_LOCAL == "local"
        assert BACKEND_MODE_REMOTE == "remote"

    def test_default_url(self):
        assert DEFAULT_LOCAL_URL == "http://localhost:8000"


# ===========================================================================
# Test: API client uses saved config
# ===========================================================================


class TestApiClientConfig:
    def test_client_uses_custom_url(self, config_dir):
        set_backend_mode(BACKEND_MODE_REMOTE)
        set_backend_url("https://remote.example.com:8000")
        set_api_key("pgv_test_key")

        from desktop_app.utils.api_client import APIClient
        client = APIClient(
            base_url=get_backend_url(),
            api_key=get_api_key(),
        )
        assert client.base_url == "https://remote.example.com:8000"
        assert client.api_base == "https://remote.example.com:8000/api/v1"
        assert client._api_key == "pgv_test_key"

    def test_client_local_defaults(self, config_dir):
        from desktop_app.utils.api_client import APIClient
        client = APIClient(
            base_url=get_backend_url(),
            api_key=None,
        )
        assert client.base_url == "http://localhost:8000"
        assert client._api_key is None
