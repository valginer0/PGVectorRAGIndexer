"""
Tests for Large Organization Licensing & Enforcement.

Covers:
- AggregatedLicense dataclass
- load_all_licenses() — seat summation, edition elevation, expired/invalid key handling
- server_settings_store multi-key helpers (get/add/remove)
- count_active_users()
- GET /api/v1/license/usage endpoint
- LicenseOverageMiddleware — headers injected / suppressed
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
)
from license_utils import is_expired

TEST_SECRET = "test-secret-large-org-only"


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
