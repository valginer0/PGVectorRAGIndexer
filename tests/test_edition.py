"""
Tests for the edition helpers module (desktop UI feature gating).

Tests cover:
- is_feature_available() returns correct values for Community vs Team
- TEAM_FEATURES map completeness
- get_edition_display() returns correct info for each edition
- open_pricing_page() calls webbrowser
"""

import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from license import (
    Edition,
    LicenseInfo,
    COMMUNITY_LICENSE,
    set_current_license,
    reset_license,
)
from desktop_app.utils.edition import (
    is_feature_available,
    get_edition_display,
    open_pricing_page,
    TEAM_FEATURES,
    PRICING_URL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_license_state():
    """Reset global license state before and after each test."""
    reset_license()
    yield
    reset_license()


def _set_community():
    """Set the global license to Community."""
    set_current_license(COMMUNITY_LICENSE)


def _set_team(**kwargs):
    """Set the global license to a valid Team license."""
    defaults = {
        "edition": Edition.TEAM,
        "org_name": "Test Org",
        "seats": 10,
        "expiry_timestamp": time.time() + 86400 * 90,
        "issued_at": time.time(),
        "key_id": "test-key",
    }
    defaults.update(kwargs)
    set_current_license(LicenseInfo(**defaults))


# ===========================================================================
# Test: TEAM_FEATURES map
# ===========================================================================


class TestTeamFeaturesMap:
    def test_map_is_not_empty(self):
        assert len(TEAM_FEATURES) > 0

    def test_all_values_are_strings(self):
        for key, desc in TEAM_FEATURES.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(desc, str), f"Description for {key!r} is not a string"
            assert len(desc) > 0, f"Description for {key!r} is empty"

    def test_known_features_present(self):
        """Key Team features from V5 must be in the map."""
        expected = [
            "scheduled_indexing",
            "multi_user",
            "split_deployment",
            "remote_backend",
            "audit_log",
            "client_identity",
            "path_mapping",
            "rbac",
        ]
        for feature in expected:
            assert feature in TEAM_FEATURES, f"Missing feature: {feature}"


# ===========================================================================
# Test: is_feature_available
# ===========================================================================


class TestIsFeatureAvailable:
    def test_community_feature_always_available(self):
        """Features not in TEAM_FEATURES are always available."""
        _set_community()
        assert is_feature_available("search") is True
        assert is_feature_available("index") is True
        assert is_feature_available("nonexistent_feature") is True

    def test_team_feature_blocked_on_community(self):
        """Team features are blocked when running Community edition."""
        _set_community()
        for feature in TEAM_FEATURES:
            assert is_feature_available(feature) is False, (
                f"Feature {feature!r} should be blocked on Community"
            )

    def test_team_feature_available_on_team(self):
        """Team features are available with a valid Team license."""
        _set_team()
        for feature in TEAM_FEATURES:
            assert is_feature_available(feature) is True, (
                f"Feature {feature!r} should be available on Team"
            )

    def test_community_feature_available_on_team(self):
        """Community features remain available on Team edition."""
        _set_team()
        assert is_feature_available("search") is True
        assert is_feature_available("nonexistent_feature") is True


# ===========================================================================
# Test: get_edition_display
# ===========================================================================


class TestGetEditionDisplay:
    def test_community_display(self):
        _set_community()
        info = get_edition_display()
        assert info["edition_label"] == "Community Edition"
        assert info["is_team"] is False
        assert info["org_name"] == ""
        assert info["seats"] == 0
        assert info["expiry_warning"] is False

    def test_team_display(self):
        _set_team(org_name="Acme Corp", seats=25)
        info = get_edition_display()
        assert info["edition_label"] == "Team Edition"
        assert info["is_team"] is True
        assert info["org_name"] == "Acme Corp"
        assert info["seats"] == 25
        assert info["expiry_warning"] is False

    def test_team_expiry_warning_when_near(self):
        """Expiry warning when < 30 days remaining."""
        _set_team(expiry_timestamp=time.time() + 86400 * 15)
        info = get_edition_display()
        assert info["is_team"] is True
        assert info["expiry_warning"] is True
        assert info["days_left"] <= 30

    def test_team_no_expiry_warning_when_far(self):
        """No expiry warning when > 30 days remaining."""
        _set_team(expiry_timestamp=time.time() + 86400 * 90)
        info = get_edition_display()
        assert info["expiry_warning"] is False
        assert info["days_left"] > 30

    def test_warning_text_from_license(self):
        """Warning text is passed through from LicenseInfo."""
        set_current_license(LicenseInfo(warning="Test warning message"))
        info = get_edition_display()
        assert info["warning_text"] == "Test warning message"

    def test_no_warning_text_when_clean(self):
        _set_team()
        info = get_edition_display()
        assert info["warning_text"] == ""


# ===========================================================================
# Test: open_pricing_page
# ===========================================================================


class TestOpenPricingPage:
    def test_opens_correct_url(self):
        with patch("desktop_app.utils.edition.webbrowser.open") as mock_open:
            open_pricing_page()
            mock_open.assert_called_once_with(PRICING_URL)

    def test_pricing_url_is_valid(self):
        assert PRICING_URL.startswith("https://")
