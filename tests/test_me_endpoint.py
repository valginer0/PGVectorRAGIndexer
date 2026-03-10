"""Tests for GET /api/v1/me endpoint."""

import pytest
from unittest.mock import patch, MagicMock

from routers.identity_api import get_current_identity


@pytest.mark.asyncio
async def test_me_loopback_returns_admin():
    """Loopback mode (no API key) returns synthetic admin."""
    request = MagicMock()
    result = await get_current_identity(request=request, key_record=None)
    assert result["auth_mode"] == "loopback"
    assert result["role"] == "admin"
    assert "system.admin" in result["permissions"]
    assert result["user"] is None


@pytest.mark.asyncio
async def test_me_api_key_no_user():
    """API key exists but no user linked to it."""
    request = MagicMock()
    key_record = {"id": 42, "name": "test-key"}

    with patch("users.get_user_by_api_key", return_value=None):
        result = await get_current_identity(request=request, key_record=key_record)

    assert result["auth_mode"] == "api_key"
    assert result["role"] is None
    assert result["permissions"] == []
    assert result["user"] is None


@pytest.mark.asyncio
async def test_me_api_key_with_user():
    """API key linked to a user returns their identity and permissions."""
    request = MagicMock()
    key_record = {"id": 42, "name": "test-key"}
    user = {
        "id": "user-1",
        "email": "alice@example.com",
        "display_name": "Alice",
        "role": "admin",
    }

    with patch("users.get_user_by_api_key", return_value=user), \
         patch("role_permissions.get_role_permissions", return_value=["system.admin", "docs.read"]):
        result = await get_current_identity(request=request, key_record=key_record)

    assert result["auth_mode"] == "api_key"
    assert result["role"] == "admin"
    assert "system.admin" in result["permissions"]
    assert result["user"]["id"] == "user-1"
    assert result["user"]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_me_api_key_user_no_role():
    """User exists but has empty role — permissions should be empty."""
    request = MagicMock()
    key_record = {"id": 42, "name": "test-key"}
    user = {
        "id": "user-2",
        "email": "bob@example.com",
        "display_name": "Bob",
        "role": "",
    }

    with patch("users.get_user_by_api_key", return_value=user):
        result = await get_current_identity(request=request, key_record=key_record)

    assert result["permissions"] == []
    assert result["role"] == ""
    assert result["user"]["id"] == "user-2"
