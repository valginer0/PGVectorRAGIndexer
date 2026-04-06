"""
Tests for Large Organization Licensing & Enforcement.

Covers:
- AggregatedLicense dataclass
- load_all_licenses() — seat summation, edition elevation, expired/invalid key handling
- server_settings_store multi-key helpers (get/add/remove)
- count_active_users()
- GET /api/v1/license/usage endpoint (unit + HTTP integration)
- POST /api/v1/license/install action=add|replace (HTTP integration)
- DELETE /api/v1/license/{kid} (HTTP integration)
- LicenseOverageMiddleware — headers injected / suppressed
- Desktop overage banner — headless widget logic
"""

import os
import sys
import time
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from typing import List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # PyJWT

from license import (
    Edition,
    LicenseInfo,
    AggregatedLicense,
    load_all_licenses,
    validate_license_key,
    reset_license,
)
from license_utils import is_expired

TEST_SECRET = "test-secret-large-org-only"


# ---------------------------------------------------------------------------
# Shared ASGI test app (mirrors test_api_license.py pattern)
# ---------------------------------------------------------------------------

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("API_REQUIRE_AUTH", "false")

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from httpx import AsyncClient, ASGITransport
from routers.system_api import system_app_router, system_v1_router

_test_app = FastAPI()


@_test_app.exception_handler(HTTPException)
async def _http_exc(request, exc):
    detail = exc.detail
    error_code = "GENERIC_HTTP_ERROR"
    message = str(detail)
    details = None
    if isinstance(detail, dict):
        error_code = detail.get("error_code", error_code)
        message = detail.get("message", message)
        details = detail.get("details")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": error_code, "message": message, "details": details},
    )


_test_app.include_router(system_app_router)
_test_app.include_router(system_v1_router, prefix="/api/v1")


@pytest.fixture
async def http_client():
    """Async HTTP client against the minimal ASGI app."""
    reset_license()
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as ac:
        yield ac
    reset_license()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(
    edition="team",
    org="Test Org",
    seats=5,
    days=90,
    secret=TEST_SECRET,
    kid="key-001",
) -> str:
    now = time.time()
    return jwt.encode(
        {
            "edition": edition,
            "org": org,
            "seats": seats,
            "iat": int(now),
            "exp": int(now + days * 86400),
            "kid": kid,
        },
        secret,
        algorithm="HS256",
    )


def _make_expired_key(kid="expired-001", secret=TEST_SECRET) -> str:
    now = time.time()
    return jwt.encode(
        {
            "edition": "team",
            "org": "Expired Org",
            "seats": 5,
            "iat": int(now - 200),
            "exp": int(now - 100),
            "kid": kid,
        },
        secret,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# AggregatedLicense dataclass
# ---------------------------------------------------------------------------


class TestAggregatedLicense:
    def test_default_is_community(self):
        agg = AggregatedLicense()
        assert agg.edition == Edition.COMMUNITY
        assert agg.seats == 0
        assert not agg.is_team
        assert agg.active_key_ids == []

    def test_is_team_for_team_edition(self):
        agg = AggregatedLicense(edition=Edition.TEAM, seats=10)
        assert agg.is_team

    def test_is_team_for_org_edition(self):
        agg = AggregatedLicense(edition=Edition.ORGANIZATION, seats=25)
        assert agg.is_team

    def test_to_dict_community(self):
        agg = AggregatedLicense()
        d = agg.to_dict()
        assert d["edition"] == "community"
        assert d["seats"] == 0
        assert d["stacked_keys"] == 0

    def test_to_dict_stacked(self):
        agg = AggregatedLicense(
            edition=Edition.ORGANIZATION,
            seats=50,
            active_key_ids=["k1", "k2"],
            org_name="BigCorp",
        )
        d = agg.to_dict()
        assert d["edition"] == "organization"
        assert d["seats"] == 50
        assert d["stacked_keys"] == 2
        assert d["org_name"] == "BigCorp"

    def test_warning_in_to_dict(self):
        agg = AggregatedLicense(warning="Key expired")
        d = agg.to_dict()
        assert "warning" in d
        assert "expired" in d["warning"]


# ---------------------------------------------------------------------------
# load_all_licenses()
# ---------------------------------------------------------------------------


class TestLoadAllLicenses:

    def _patch_keys(self, keys: List[str], fs_path_exists=False):
        """Return a context manager that mocks key sources."""
        import unittest.mock as mock
        patches = [
            mock.patch(
                "license.get_server_license_keys",
                return_value=keys,
                create=True,
            ),
            mock.patch(
                "license.get_license_file_path",
                return_value=Path("/nonexistent/license.key"),
            ),
        ]
        return patches

    def test_no_keys_returns_community(self):
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.edition == Edition.COMMUNITY
        assert agg.seats == 0
        assert not agg.is_team

    def test_single_key_sums_correctly(self):
        key = _make_key(seats=5, kid="k1")
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[key]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.seats == 5
        assert agg.edition == Edition.TEAM
        assert "k1" in agg.active_key_ids

    def test_two_keys_sum_seats(self):
        k1 = _make_key(seats=5, kid="k1")
        k2 = _make_key(seats=5, kid="k2")
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[k1, k2]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.seats == 10
        assert len(agg.active_key_ids) == 2

    def test_expired_key_excluded_from_sum(self):
        valid = _make_key(seats=5, kid="valid")
        expired = _make_expired_key(kid="expired")
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[valid, expired]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.seats == 5
        assert "valid" in agg.active_key_ids
        assert "expired" not in agg.active_key_ids
        assert any("expired" in w.lower() for w in agg.warnings)

    def test_invalid_key_excluded_with_warning(self):
        valid = _make_key(seats=5, kid="good")
        invalid = "not.a.jwt"
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[valid, invalid]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.seats == 5
        assert len(agg.warnings) == 1

    def test_all_expired_returns_community(self):
        e1 = _make_expired_key(kid="e1")
        e2 = _make_expired_key(kid="e2")
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[e1, e2]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.edition == Edition.COMMUNITY
        assert agg.seats == 0

    def test_edition_elevated_to_highest(self):
        team_key = _make_key(edition="team", seats=5, kid="t1")
        org_key = _make_key(edition="organization", seats=25, kid="o1")
        with patch("license.get_license_file_path", return_value=Path("/nonexistent/x")), \
             patch("server_settings_store.get_server_license_keys", return_value=[team_key, org_key]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.edition == Edition.ORGANIZATION
        assert agg.seats == 30

    def test_deduplication_fs_key_already_in_db(self, tmp_path):
        """Filesystem key that duplicates a DB key must not be counted twice."""
        key = _make_key(seats=5, kid="k1")
        key_file = tmp_path / "license.key"
        key_file.write_text(key)
        with patch("license.get_license_file_path", return_value=key_file), \
             patch("server_settings_store.get_server_license_keys", return_value=[key]):
            agg = load_all_licenses(signing_secret=TEST_SECRET)
        assert agg.seats == 5  # counted once, not twice


# ---------------------------------------------------------------------------
# server_settings_store multi-key helpers
# ---------------------------------------------------------------------------


class TestServerSettingsStoreMultiKey:
    """Unit-test the multi-key helpers with a mocked get/set_server_setting."""

    def _settings(self):
        """In-memory settings store fixture."""
        store = {}

        def _get(key):
            return store.get(key)

        def _set(key, value):
            store[key] = value

        return store, _get, _set

    def test_get_returns_empty_when_nothing_stored(self):
        from server_settings_store import get_server_license_keys
        store, _get, _set = self._settings()
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            assert get_server_license_keys() == []

    def test_add_stores_key(self):
        from server_settings_store import get_server_license_keys, add_server_license_key
        store, _get, _set = self._settings()
        key = _make_key(kid="k1")
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            add_server_license_key(key)
            keys = get_server_license_keys()
        assert len(keys) == 1
        assert keys[0] == key

    def test_add_deduplicates_by_kid(self):
        from server_settings_store import get_server_license_keys, add_server_license_key
        store, _get, _set = self._settings()
        key = _make_key(kid="k1")
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            add_server_license_key(key)
            add_server_license_key(key)  # duplicate
            keys = get_server_license_keys()
        assert len(keys) == 1

    def test_add_two_different_keys(self):
        from server_settings_store import get_server_license_keys, add_server_license_key
        store, _get, _set = self._settings()
        k1 = _make_key(kid="k1")
        k2 = _make_key(kid="k2")
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            add_server_license_key(k1)
            add_server_license_key(k2)
            keys = get_server_license_keys()
        assert len(keys) == 2

    def test_remove_by_kid(self):
        from server_settings_store import (
            get_server_license_keys, add_server_license_key, remove_server_license_key
        )
        store, _get, _set = self._settings()
        k1 = _make_key(kid="k1")
        k2 = _make_key(kid="k2")
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            add_server_license_key(k1)
            add_server_license_key(k2)
            removed = remove_server_license_key("k1")
            keys = get_server_license_keys()
        assert removed is True
        assert len(keys) == 1

    def test_remove_nonexistent_returns_false(self):
        from server_settings_store import (
            get_server_license_keys, add_server_license_key, remove_server_license_key
        )
        store, _get, _set = self._settings()
        k1 = _make_key(kid="k1")
        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            add_server_license_key(k1)
            removed = remove_server_license_key("nonexistent-kid")
        assert removed is False

    def test_migrates_legacy_single_key(self):
        """Old installations with ``license_key`` dict format are migrated transparently."""
        from server_settings_store import get_server_license_keys
        key = _make_key(kid="legacy")
        legacy_store = {"license_key": {"token": key}}

        def _get(k):
            return legacy_store.get(k)

        def _set(k, v):
            legacy_store[k] = v

        with patch("server_settings_store.get_server_setting", side_effect=_get), \
             patch("server_settings_store.set_server_setting", side_effect=_set):
            keys = get_server_license_keys()
        assert len(keys) == 1
        assert keys[0] == key


# ---------------------------------------------------------------------------
# count_active_users()
# ---------------------------------------------------------------------------


class TestCountActiveUsers:
    def test_returns_count_from_db(self):
        from users import count_active_users

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (7,)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        with patch("users._get_db_connection", return_value=mock_conn):
            count = count_active_users()
        assert count == 7

    def test_returns_zero_on_db_error(self):
        from users import count_active_users

        with patch("users._get_db_connection", side_effect=Exception("DB down")):
            count = count_active_users()
        assert count == 0


# ---------------------------------------------------------------------------
# GET /api/v1/license/usage — endpoint logic
# ---------------------------------------------------------------------------


class TestLicenseUsageEndpoint:
    def test_overage_arithmetic_team(self):
        """overage = max(0, active - licensed)."""
        agg = AggregatedLicense(edition=Edition.TEAM, seats=5, active_key_ids=["k1"])
        import asyncio
        from routers.system_api import get_license_usage
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=8):
            result = asyncio.get_event_loop().run_until_complete(get_license_usage())
        assert result["licensed_seats"] == 5
        assert result["active_seats"] == 8
        assert result["overage"] == 3

    def test_no_overage_when_within_limit(self):
        agg = AggregatedLicense(edition=Edition.TEAM, seats=25, active_key_ids=["k1"])
        import asyncio
        from routers.system_api import get_license_usage
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=20):
            result = asyncio.get_event_loop().run_until_complete(get_license_usage())
        assert result["overage"] == 0

    def test_community_edition_always_zero_overage(self):
        agg = AggregatedLicense(edition=Edition.COMMUNITY)
        import asyncio
        from routers.system_api import get_license_usage
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=999):
            result = asyncio.get_event_loop().run_until_complete(get_license_usage())
        assert result["overage"] == 0
        assert result["licensed_seats"] == 0
        assert result["active_seats"] == 0


# ---------------------------------------------------------------------------
# LicenseOverageMiddleware
# ---------------------------------------------------------------------------


class TestLicenseOverageMiddleware:
    def _make_response(self):
        from starlette.responses import Response
        return Response(content="ok", status_code=200)

    def _reset_cache(self):
        from license_overage import _cache
        _cache._last_refresh = 0.0
        _cache._overage = 0

    def test_headers_added_when_overage(self):
        self._reset_cache()
        from license_overage import _cache
        _cache._overage = 3
        _cache._licensed = 5
        _cache._active = 8
        _cache._last_refresh = time.monotonic()  # mark as fresh

        import asyncio
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from license_overage import LicenseOverageMiddleware

        async def homepage(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(LicenseOverageMiddleware)

        client = TestClient(app)
        resp = client.get("/")
        assert resp.headers.get("x-license-overage") == "true"
        assert resp.headers.get("x-license-overage-count") == "3"
        assert "Warning" in resp.headers

    def test_no_headers_when_no_overage(self):
        self._reset_cache()
        from license_overage import _cache
        _cache._overage = 0
        _cache._last_refresh = time.monotonic()

        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse
        from license_overage import LicenseOverageMiddleware

        async def homepage(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(LicenseOverageMiddleware)

        client = TestClient(app)
        resp = client.get("/")
        assert "x-license-overage" not in resp.headers

    def test_cache_refreshes_when_stale(self):
        self._reset_cache()
        from license_overage import _cache, invalidate_overage_cache

        invalidate_overage_cache()  # force stale

        agg = AggregatedLicense(edition=Edition.TEAM, seats=5, active_key_ids=["k1"])

        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=3):
            _cache.refresh()

        assert _cache.overage == 0  # 3 active, 5 licensed

    def test_invalidate_overage_cache(self):
        from license_overage import _cache, invalidate_overage_cache
        _cache._last_refresh = time.monotonic()
        assert not _cache.is_stale()
        invalidate_overage_cache()
        assert _cache.is_stale()


# ---------------------------------------------------------------------------
# HTTP integration tests — new endpoints through ASGI transport
# ---------------------------------------------------------------------------


class TestLicenseUsageEndpointHTTP:
    """Hit GET /api/v1/license/usage via real HTTP through the ASGI stack."""

    @pytest.mark.asyncio
    async def test_community_returns_zeros(self, http_client):
        agg = AggregatedLicense(edition=Edition.COMMUNITY)
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=0):
            resp = await http_client.get("/api/v1/license/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overage"] == 0
        assert data["licensed_seats"] == 0
        assert data["active_seats"] == 0
        assert data["edition"] == "community"

    @pytest.mark.asyncio
    async def test_team_within_limit(self, http_client):
        agg = AggregatedLicense(edition=Edition.TEAM, seats=10, active_key_ids=["k1"])
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=7):
            resp = await http_client.get("/api/v1/license/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["licensed_seats"] == 10
        assert data["active_seats"] == 7
        assert data["overage"] == 0

    @pytest.mark.asyncio
    async def test_overage_reflected_correctly(self, http_client):
        agg = AggregatedLicense(edition=Edition.TEAM, seats=5, active_key_ids=["k1"])
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=8):
            resp = await http_client.get("/api/v1/license/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overage"] == 3
        assert data["active_seats"] == 8
        assert data["licensed_seats"] == 5

    @pytest.mark.asyncio
    async def test_stacked_seats_combined(self, http_client):
        """Two 5-seat keys → 10 licensed seats reflected in usage endpoint."""
        agg = AggregatedLicense(
            edition=Edition.ORGANIZATION, seats=10, active_key_ids=["k1", "k2"]
        )
        with patch("license.get_current_license", return_value=agg), \
             patch("users.count_active_users", return_value=9):
            resp = await http_client.get("/api/v1/license/usage")
        data = resp.json()
        assert data["licensed_seats"] == 10
        assert data["overage"] == 0


class TestInstallEndpointHTTP:
    """POST /api/v1/license/install — action=add and action=replace via HTTP."""

    def _agg(self, seats=5):
        return AggregatedLicense(edition=Edition.TEAM, seats=seats, active_key_ids=["k1"])

    @pytest.mark.asyncio
    async def test_add_action_default(self, http_client):
        key = _make_key(seats=5, kid="k1")
        agg = self._agg(5)
        with patch("routers.system_api.is_loopback_request", return_value=True), \
             patch("license.resolve_verification_context", return_value=(TEST_SECRET, ["HS256"])), \
             patch("license.validate_license_key", return_value=MagicMock()), \
             patch("server_settings_store.add_server_license_key") as mock_add, \
             patch("license.reset_license"), \
             patch("license.load_all_licenses", return_value=agg), \
             patch("license.set_current_license"), \
             patch("server_settings_store.get_server_license_keys", return_value=[key]):
            resp = await http_client.post("/api/v1/license/install", json={"license_key": key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stored"
        assert data["action"] == "add"
        assert data["total_licensed_seats"] == 5
        mock_add.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_replace_action(self, http_client):
        key = _make_key(seats=25, kid="k-org")
        agg = AggregatedLicense(edition=Edition.ORGANIZATION, seats=25, active_key_ids=["k-org"])
        with patch("routers.system_api.is_loopback_request", return_value=True), \
             patch("license.resolve_verification_context", return_value=(TEST_SECRET, ["HS256"])), \
             patch("license.validate_license_key", return_value=MagicMock()), \
             patch("server_settings_store.set_server_license_key") as mock_set, \
             patch("license.reset_license"), \
             patch("license.load_all_licenses", return_value=agg), \
             patch("license.set_current_license"), \
             patch("server_settings_store.get_server_license_keys", return_value=[key]):
            resp = await http_client.post(
                "/api/v1/license/install",
                json={"license_key": key, "action": "replace"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "replace"
        mock_set.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, http_client):
        key = _make_key(kid="k1")
        with patch("routers.system_api.is_loopback_request", return_value=True), \
             patch("license.resolve_verification_context", return_value=(TEST_SECRET, ["HS256"])), \
             patch("license.validate_license_key", return_value=MagicMock()):
            resp = await http_client.post(
                "/api/v1/license/install",
                json={"license_key": key, "action": "delete_all"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_non_loopback_rejected(self, http_client):
        key = _make_key(kid="k1")
        with patch("routers.system_api.is_loopback_request", return_value=False):
            resp = await http_client.post("/api/v1/license/install", json={"license_key": key})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_key_rejected(self, http_client):
        with patch("routers.system_api.is_loopback_request", return_value=True):
            resp = await http_client.post("/api/v1/license/install", json={})
        assert resp.status_code == 400


class TestDeleteLicenseEndpointHTTP:
    """DELETE /api/v1/license/{kid} via HTTP."""

    @pytest.mark.asyncio
    async def test_remove_existing_key(self, http_client):
        agg = AggregatedLicense(edition=Edition.COMMUNITY)
        with patch("routers.system_api.is_loopback_request", return_value=True), \
             patch("server_settings_store.remove_server_license_key", return_value=True), \
             patch("license.reset_license"), \
             patch("license.load_all_licenses", return_value=agg), \
             patch("license.set_current_license"):
            resp = await http_client.delete("/api/v1/license/my-kid-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "removed"
        assert data["kid"] == "my-kid-123"

    @pytest.mark.asyncio
    async def test_remove_nonexistent_key_returns_404(self, http_client):
        with patch("routers.system_api.is_loopback_request", return_value=True), \
             patch("server_settings_store.remove_server_license_key", return_value=False):
            resp = await http_client.delete("/api/v1/license/no-such-kid")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_loopback_rejected(self, http_client):
        with patch("routers.system_api.is_loopback_request", return_value=False):
            resp = await http_client.delete("/api/v1/license/any-kid")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Desktop overage banner — headless unit test (no display required)
# ---------------------------------------------------------------------------


class TestOverageBannerLogic:
    """Test _check_license_overage() and _dismiss_overage_banner() without Qt display.

    We test the pure logic by patching out Qt widget calls so no QApplication
    is needed.  Visual rendering is covered by the existing slow UI test suite.
    """

    def _make_mock_window(self):
        """Build a minimal stand-in for MainWindow with just the banner attributes."""
        win = MagicMock()
        win._overage_dismissed = False
        win._overage_banner = MagicMock()
        win._overage_banner_text = MagicMock()
        win.api_client = MagicMock()
        # Bind the real method implementations to our mock object
        from desktop_app.ui.main_window import MainWindow
        win._check_license_overage = MainWindow._check_license_overage.__get__(win, type(win))
        win._dismiss_overage_banner = MainWindow._dismiss_overage_banner.__get__(win, type(win))
        return win

    def test_banner_shown_when_overage(self):
        win = self._make_mock_window()
        win.api_client.get_license_usage.return_value = {
            "overage": 3, "active_seats": 8, "licensed_seats": 5
        }
        win._check_license_overage()
        win._overage_banner.setVisible.assert_called_with(True)

    def test_banner_hidden_when_no_overage(self):
        win = self._make_mock_window()
        win.api_client.get_license_usage.return_value = {
            "overage": 0, "active_seats": 4, "licensed_seats": 5
        }
        win._check_license_overage()
        win._overage_banner.setVisible.assert_called_with(False)

    def test_banner_not_shown_after_dismiss(self):
        win = self._make_mock_window()
        win._overage_dismissed = True
        win.api_client.get_license_usage.return_value = {
            "overage": 5, "active_seats": 10, "licensed_seats": 5
        }
        win._check_license_overage()
        win._overage_banner.setVisible.assert_not_called()

    def test_dismiss_sets_flag_and_hides(self):
        win = self._make_mock_window()
        win._dismiss_overage_banner()
        assert win._overage_dismissed is True
        win._overage_banner.setVisible.assert_called_with(False)

    def test_api_error_does_not_raise(self):
        win = self._make_mock_window()
        win.api_client.get_license_usage.side_effect = RuntimeError("timeout")
        win._check_license_overage()  # must not raise
        win._overage_banner.setVisible.assert_not_called()

    def test_banner_text_contains_seat_numbers(self):
        win = self._make_mock_window()
        win.api_client.get_license_usage.return_value = {
            "overage": 3, "active_seats": 28, "licensed_seats": 25
        }
        win._check_license_overage()
        call_args = win._overage_banner_text.setText.call_args[0][0]
        assert "28" in call_args
        assert "25" in call_args
