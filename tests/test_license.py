"""
Unit tests for the license key validation module.

Tests cover:
- Valid key validation
- Expired key handling
- Missing key file → Community
- Tampered key detection
- Malformed key handling
- Missing JWT claims
- Platform-specific path resolution
- Global license state management
- Key generation tool
"""

import os
import sys
import time
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt  # PyJWT

from license import (
    Edition,
    LicenseInfo,
    LicenseError,
    LicenseExpiredError,
    LicenseInvalidError,
    COMMUNITY_LICENSE,
    validate_license_key,
    load_license,
    get_license_file_path,
    get_current_license,
    set_current_license,
    reset_license,
    is_team_edition,
)

# Test signing secret (NOT a real secret)
TEST_SECRET = "test-secret-for-unit-tests-only"


# ---------------------------------------------------------------------------
# Helper: generate test keys
# ---------------------------------------------------------------------------


def _make_key(
    edition="team",
    org="Test Org",
    seats=5,
    days=90,
    secret=TEST_SECRET,
    extra_claims=None,
) -> str:
    """Generate a test JWT license key."""
    now = time.time()
    payload = {
        "edition": edition,
        "org": org,
        "seats": seats,
        "iat": int(now),
        "exp": int(now + (days * 86400)),
        "jti": "test-key-id",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def _make_expired_key(secret=TEST_SECRET) -> str:
    """Generate an expired test key."""
    now = time.time()
    payload = {
        "edition": "team",
        "org": "Expired Org",
        "seats": 3,
        "iat": int(now - 200),
        "exp": int(now - 100),  # Expired 100 seconds ago
        "jti": "expired-key",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ===========================================================================
# Test: Edition enum
# ===========================================================================


class TestEdition:
    def test_community_value(self):
        assert Edition.COMMUNITY.value == "community"

    def test_team_value(self):
        assert Edition.TEAM.value == "team"

    def test_string_enum(self):
        """Edition is a string enum for easy serialization."""
        assert Edition.COMMUNITY == "community"
        assert Edition.TEAM == "team"


# ===========================================================================
# Test: LicenseInfo
# ===========================================================================


class TestLicenseInfo:
    def test_default_is_community(self):
        info = LicenseInfo()
        assert info.edition == Edition.COMMUNITY
        assert info.org_name == ""
        assert info.seats == 0
        assert not info.is_team

    def test_community_singleton(self):
        assert COMMUNITY_LICENSE.edition == Edition.COMMUNITY
        assert not COMMUNITY_LICENSE.is_team

    def test_team_license(self):
        info = LicenseInfo(
            edition=Edition.TEAM,
            org_name="Acme Corp",
            seats=10,
            expiry_timestamp=time.time() + 86400 * 30,
        )
        assert info.is_team
        assert info.org_name == "Acme Corp"
        assert info.seats == 10
        assert not info.is_expired
        assert info.days_until_expiry > 0

    def test_expired_license(self):
        info = LicenseInfo(
            edition=Edition.TEAM,
            expiry_timestamp=time.time() - 100,
        )
        assert info.is_expired
        assert info.days_until_expiry <= 0

    def test_no_expiry(self):
        info = LicenseInfo()
        assert not info.is_expired
        assert info.days_until_expiry == 999

    def test_to_dict(self):
        info = LicenseInfo(
            edition=Edition.TEAM,
            org_name="Acme",
            seats=5,
            expiry_timestamp=time.time() + 86400,
        )
        d = info.to_dict()
        assert d["edition"] == "team"
        assert d["org_name"] == "Acme"
        assert d["seats"] == 5
        assert "days_until_expiry" in d
        assert "warning" not in d  # No warning

    def test_to_dict_with_warning(self):
        info = LicenseInfo(warning="Test warning")
        d = info.to_dict()
        assert d["warning"] == "Test warning"


# ===========================================================================
# Test: validate_license_key
# ===========================================================================


class TestValidateLicenseKey:
    def test_valid_team_key(self):
        key = _make_key(edition="team", org="Acme Corp", seats=10)
        info = validate_license_key(key, TEST_SECRET)
        assert info.edition == Edition.TEAM
        assert info.org_name == "Acme Corp"
        assert info.seats == 10
        assert info.is_team
        assert not info.is_expired

    def test_valid_community_key(self):
        key = _make_key(edition="community", org="Solo Dev")
        info = validate_license_key(key, TEST_SECRET)
        assert info.edition == Edition.COMMUNITY
        assert not info.is_team

    def test_expired_key_raises(self):
        key = _make_expired_key()
        with pytest.raises(LicenseExpiredError):
            validate_license_key(key, TEST_SECRET)

    def test_wrong_secret_raises(self):
        key = _make_key(secret=TEST_SECRET)
        with pytest.raises(LicenseInvalidError, match="signature"):
            validate_license_key(key, "wrong-secret")

    def test_malformed_key_raises(self):
        with pytest.raises(LicenseInvalidError, match="malformed"):
            validate_license_key("not.a.jwt.at.all", TEST_SECRET)

    def test_empty_key_raises(self):
        with pytest.raises(LicenseInvalidError, match="empty"):
            validate_license_key("", TEST_SECRET)

    def test_whitespace_key_raises(self):
        with pytest.raises(LicenseInvalidError, match="empty"):
            validate_license_key("   ", TEST_SECRET)

    def test_no_secret_raises(self):
        key = _make_key()
        with pytest.raises(LicenseError, match="signing secret"):
            validate_license_key(key, "")

    def test_invalid_edition_raises(self):
        key = _make_key(edition="enterprise")
        with pytest.raises(LicenseInvalidError, match="Invalid edition"):
            validate_license_key(key, TEST_SECRET)

    def test_team_without_org_raises(self):
        key = _make_key(edition="team", org="")
        with pytest.raises(LicenseInvalidError, match="org"):
            validate_license_key(key, TEST_SECRET)

    def test_key_id_from_jti(self):
        key = _make_key()
        info = validate_license_key(key, TEST_SECRET)
        assert info.key_id == "test-key-id"

    def test_key_id_from_kid(self):
        key = _make_key(extra_claims={"kid": "custom-kid"})
        info = validate_license_key(key, TEST_SECRET)
        # kid takes precedence since it's checked first in the payload
        assert info.key_id == "custom-kid"


# ===========================================================================
# Test: load_license
# ===========================================================================


class TestLoadLicense:
    def test_missing_file_returns_community(self, tmp_path):
        """No key file → Community, no error."""
        info = load_license(
            signing_secret=TEST_SECRET,
            key_path=tmp_path / "nonexistent" / "license.key",
        )
        assert info.edition == Edition.COMMUNITY
        assert not info.warning

    def test_valid_key_file(self, tmp_path):
        """Valid key on disk → Team edition."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key())
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.TEAM
        assert info.org_name == "Test Org"

    def test_expired_key_file_returns_community_with_warning(self, tmp_path):
        """Expired key → Community with warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_expired_key())
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.COMMUNITY
        assert "expired" in info.warning.lower()

    def test_tampered_key_returns_community_with_warning(self, tmp_path):
        """Tampered key (wrong secret) → Community with warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key(secret="different-secret"))
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.COMMUNITY
        assert "signature" in info.warning.lower() or "invalid" in info.warning.lower()

    def test_corrupted_key_returns_community_with_warning(self, tmp_path):
        """Corrupted/garbage key → Community with warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text("this is not a jwt token at all")
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.COMMUNITY
        assert info.warning

    def test_empty_key_file_returns_community_with_warning(self, tmp_path):
        """Empty key file → Community with warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text("")
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.COMMUNITY
        assert "empty" in info.warning.lower()

    def test_no_secret_returns_community_with_warning(self, tmp_path):
        """Key file exists but no signing secret → Community with warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key())
        info = load_license(signing_secret="", key_path=key_file)
        assert info.edition == Edition.COMMUNITY
        assert "LICENSE_SIGNING_SECRET" in info.warning

    def test_secret_from_env(self, tmp_path):
        """Signing secret read from environment variable."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key())
        with patch.dict(os.environ, {"LICENSE_SIGNING_SECRET": TEST_SECRET}):
            info = load_license(key_path=key_file)
        assert info.edition == Edition.TEAM

    def test_expiry_warning_when_near_expiry(self, tmp_path):
        """License expiring within 14 days gets a warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key(days=7))  # Expires in 7 days
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.TEAM  # Still Team
        assert "expires in" in info.warning.lower()

    def test_no_expiry_warning_when_far_from_expiry(self, tmp_path):
        """License not expiring soon has no warning."""
        key_file = tmp_path / "license.key"
        key_file.write_text(_make_key(days=90))
        info = load_license(signing_secret=TEST_SECRET, key_path=key_file)
        assert info.edition == Edition.TEAM
        assert not info.warning


# ===========================================================================
# Test: Platform paths
# ===========================================================================


class TestPlatformPaths:
    @patch("license.platform.system", return_value="Linux")
    def test_linux_path(self, mock_system):
        path = get_license_file_path()
        assert ".pgvector-license" in str(path)
        assert path.name == "license.key"

    @patch("license.platform.system", return_value="Darwin")
    def test_macos_path(self, mock_system):
        path = get_license_file_path()
        assert ".pgvector-license" in str(path)
        assert path.name == "license.key"

    @patch("license.platform.system", return_value="Windows")
    @patch.dict(os.environ, {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"})
    def test_windows_path(self, mock_system):
        path = get_license_file_path()
        assert "PGVectorRAGIndexer" in str(path)
        assert path.name == "license.key"


# ===========================================================================
# Test: Global state
# ===========================================================================


class TestGlobalState:
    def setup_method(self):
        """Reset license state before each test."""
        reset_license()

    def test_get_current_license_default(self):
        """Default license is Community when no key file exists."""
        # Patch to ensure no key file is found
        with patch("license.get_license_file_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/license.key")
            info = get_current_license()
        assert info.edition == Edition.COMMUNITY

    def test_set_and_get_license(self):
        """set_current_license / get_current_license round-trip."""
        team_license = LicenseInfo(edition=Edition.TEAM, org_name="Test")
        set_current_license(team_license)
        assert get_current_license().edition == Edition.TEAM
        assert get_current_license().org_name == "Test"

    def test_is_team_edition(self):
        set_current_license(LicenseInfo(edition=Edition.TEAM))
        assert is_team_edition()

    def test_is_not_team_edition(self):
        set_current_license(COMMUNITY_LICENSE)
        assert not is_team_edition()

    def test_reset_forces_reload(self):
        """reset_license() forces reload on next access."""
        set_current_license(LicenseInfo(edition=Edition.TEAM))
        assert is_team_edition()
        reset_license()
        with patch("license.get_license_file_path") as mock_path:
            mock_path.return_value = Path("/nonexistent/license.key")
            assert not is_team_edition()


# ===========================================================================
# Test: Key generation tool
# ===========================================================================


class TestKeyGeneration:
    def test_generate_license_key(self):
        """generate_license_key produces a valid JWT."""
        from generate_license_key import generate_license_key

        token = generate_license_key(
            signing_secret=TEST_SECRET,
            edition="team",
            org_name="Gen Test Org",
            seats=15,
            days=30,
        )

        # Decode and verify
        payload = jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
        assert payload["edition"] == "team"
        assert payload["org"] == "Gen Test Org"
        assert payload["seats"] == 15
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_generated_key_validates(self):
        """Key from generator passes validate_license_key."""
        from generate_license_key import generate_license_key

        token = generate_license_key(
            signing_secret=TEST_SECRET,
            edition="team",
            org_name="Round Trip Org",
            seats=5,
            days=90,
        )
        info = validate_license_key(token, TEST_SECRET)
        assert info.edition == Edition.TEAM
        assert info.org_name == "Round Trip Org"
        assert info.seats == 5
