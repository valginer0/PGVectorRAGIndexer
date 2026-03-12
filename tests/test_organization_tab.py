"""Automated QA tests for the Organization tab, settings integration, and widget-level behavior.

Requires: pytest-qt, QT_QPA_PLATFORM=offscreen (set in conftest or environment).
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Force offscreen rendering before any Qt import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop_app.utils.api_client import APIClient, CapabilityStatus, ProbeResult
from desktop_app.utils.server_capabilities import ServerCapabilities, _PROBES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication for all tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def api_client():
    return APIClient(base_url="http://test-server")


@pytest.fixture
def caps(api_client):
    return ServerCapabilities(api_client)


def _make_probe_fn(status_map=None, default_status=CapabilityStatus.AVAILABLE):
    """Create a probe function that returns different statuses per endpoint."""
    status_map = status_map or {}

    def fake_probe(path, timeout=3):
        for key, probe_path in _PROBES.items():
            if probe_path in path or path in probe_path:
                st = status_map.get(key, default_status)
                if st == CapabilityStatus.AVAILABLE:
                    body = {"permissions": ["system.admin"]} if "/me" in path else {}
                    return ProbeResult(status=st, body=body, status_code=200)
                elif st == CapabilityStatus.UNAUTHORIZED:
                    return ProbeResult(status=st, status_code=401)
                elif st == CapabilityStatus.NOT_SUPPORTED:
                    return ProbeResult(status=st, status_code=404)
                elif st == CapabilityStatus.UNREACHABLE:
                    return ProbeResult(status=st)
                else:
                    return ProbeResult(status=st)
        return ProbeResult(status=default_status, body={}, status_code=200)

    return fake_probe


def _noop_refresh(self):
    """No-op replacement for panel refresh() to avoid real API calls."""
    pass


@pytest.fixture
def org_tab(qapp, api_client):
    """Create an OrganizationTab with panel refreshes mocked out."""
    from desktop_app.ui.admin_tab import (
        OrganizationTab, _OverviewPanel, _UsersRolesPanel,
        _PermissionsPanel, _RetentionPanel, _ActivityPanel,
    )
    with patch.object(_OverviewPanel, "refresh", _noop_refresh), \
         patch.object(_UsersRolesPanel, "refresh", _noop_refresh), \
         patch.object(_PermissionsPanel, "refresh", _noop_refresh), \
         patch.object(_RetentionPanel, "refresh", _noop_refresh), \
         patch.object(_ActivityPanel, "refresh", _noop_refresh):
        tab = OrganizationTab(api_client)
        yield tab
    tab.deleteLater()


@pytest.fixture
def org_tab_live(qapp, api_client):
    """OrganizationTab WITHOUT mocked panel refreshes — for testing real panel behavior.
    Tests using this must mock the individual API calls themselves."""
    from desktop_app.ui.admin_tab import OrganizationTab
    tab = OrganizationTab(api_client)
    yield tab
    tab.deleteLater()


# ---------------------------------------------------------------------------
# Settings Integration Tests
# ---------------------------------------------------------------------------

class TestSettingsIntegration:
    """Test that changing backend settings invalidates capabilities."""

    def test_on_settings_changed_invalidates_cache(self, org_tab, api_client):
        """on_settings_changed() clears cached capabilities."""
        # First, populate cache with AVAILABLE
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn()):
            org_tab.probe_and_refresh()

        assert org_tab._caps.is_available("users")
        assert org_tab._caps.is_admin()

        # Now simulate settings change — all probes return UNREACHABLE
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.on_settings_changed()

        # Cache was invalidated, then re-probed with UNREACHABLE (not cached)
        assert not org_tab._caps.is_available("users")
        assert not org_tab._caps.is_admin()
        assert org_tab._caps.get_identity() is None

    def test_on_settings_changed_triggers_reprobe(self, org_tab, api_client):
        """on_settings_changed() calls probe_all() after invalidation."""
        probe_count = 0

        def counting_probe(path, timeout=3):
            nonlocal probe_count
            probe_count += 1
            return ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)

        with patch.object(api_client, "probe_endpoint", side_effect=counting_probe), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.on_settings_changed()

        assert probe_count == len(_PROBES)

    def test_settings_signal_exists(self, qapp):
        """SettingsTab should have a backend_settings_changed signal."""
        from desktop_app.ui.settings_tab import SettingsTab
        assert hasattr(SettingsTab, "backend_settings_changed")


# ---------------------------------------------------------------------------
# Organization Tab State Machine Tests
# ---------------------------------------------------------------------------

class TestTabVisibilityStates:
    """Test _update_visibility() state transitions with real widgets."""

    def test_community_unreachable_shows_gated(self, org_tab, api_client):
        """Community edition + all unreachable → gated placeholder."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=False):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_community_server_available_shows_tabs(self, org_tab, api_client):
        """Community edition + server has org endpoints → show panels."""
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=False):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

    def test_paid_unreachable_shows_retry(self, org_tab, api_client):
        """Paid edition + all unreachable → 'cannot connect' with retry."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_paid_old_server_shows_not_supported(self, org_tab, api_client):
        """Paid edition + all NOT_SUPPORTED → 'not supported' message."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_auth_failure_shows_auth_message(self, org_tab, api_client):
        """All UNAUTHORIZED → auth configuration message (not gated/not-supported)."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_auth_failure_community_also_shows_auth_message(self, org_tab, api_client):
        """Community + all UNAUTHORIZED → auth message, not gated widget."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=False):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_all_available_shows_all_subtabs(self, org_tab, api_client):
        """All capabilities available → all sub-tabs visible."""
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "Overview" in tab_titles
        assert "Users & Roles" in tab_titles
        assert "Permissions" in tab_titles
        assert "Retention" in tab_titles
        assert "Activity" in tab_titles

    def test_partial_available_shows_only_available_subtabs(self, org_tab, api_client):
        """Only users+roles available → only those sub-tabs shown."""
        status_map = {
            "me": CapabilityStatus.AVAILABLE,
            "users": CapabilityStatus.AVAILABLE,
            "roles": CapabilityStatus.AVAILABLE,
            "permissions": CapabilityStatus.NOT_SUPPORTED,
            "retention": CapabilityStatus.NOT_SUPPORTED,
            "activity": CapabilityStatus.NOT_SUPPORTED,
        }
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "Overview" in tab_titles
        assert "Users & Roles" in tab_titles
        assert "Permissions" not in tab_titles
        assert "Retention" not in tab_titles
        assert "Activity" not in tab_titles

    def test_subtabs_rebuild_on_capability_change(self, org_tab, api_client):
        """Sub-tabs are rebuilt when capabilities change — no stale tabs."""
        # First: all available
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()
        assert org_tab._sub_tabs.count() == 5  # Overview + 4 sub-tabs

        # Second: only users available
        status_map = {k: CapabilityStatus.NOT_SUPPORTED for k in _PROBES}
        status_map["me"] = CapabilityStatus.AVAILABLE
        status_map["users"] = CapabilityStatus.AVAILABLE
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab._on_refresh()

        assert org_tab._sub_tabs.count() == 2  # Overview + Users & Roles


# ---------------------------------------------------------------------------
# Admin Write Control Visibility Tests
# ---------------------------------------------------------------------------

class TestAdminWriteControls:
    """Test that write buttons are visible only for admins."""

    def test_admin_user_sees_write_controls(self, org_tab_live, api_client):
        """Admin user → write buttons visible in Users & Roles."""
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch.object(api_client, "list_users", return_value={"users": []}), \
             patch.object(api_client, "list_roles", return_value={"roles": []}), \
             patch.object(api_client, "list_permissions", return_value={"permissions": []}), \
             patch.object(api_client, "get_retention_policy", return_value={}), \
             patch.object(api_client, "get_retention_status", return_value={}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": [], "total": 0}), \
             patch.object(api_client, "get_activity_action_types", return_value={"action_types": []}), \
             patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            org_tab_live.probe_and_refresh()

        assert org_tab_live._caps.is_admin()
        # Use isHidden() instead of isVisible() — in offscreen mode, isVisible()
        # returns False when the parent widget chain isn't shown.
        assert not org_tab_live._users_roles._admin_widget.isHidden()

    def test_non_admin_user_hides_write_controls(self, org_tab_live, api_client):
        """Non-admin user → write buttons hidden."""
        def non_admin_probe(path, timeout=3):
            if "/me" in path:
                return ProbeResult(
                    status=CapabilityStatus.AVAILABLE,
                    body={"role": "user", "permissions": ["docs.read"]},
                    status_code=200,
                )
            return ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)

        with patch.object(api_client, "probe_endpoint", side_effect=non_admin_probe), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch.object(api_client, "list_users", return_value={"users": []}), \
             patch.object(api_client, "list_roles", return_value={"roles": []}), \
             patch.object(api_client, "list_permissions", return_value={"permissions": []}), \
             patch.object(api_client, "get_retention_policy", return_value={}), \
             patch.object(api_client, "get_retention_status", return_value={}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": [], "total": 0}), \
             patch.object(api_client, "get_activity_action_types", return_value={"action_types": []}), \
             patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            org_tab_live.probe_and_refresh()

        assert not org_tab_live._caps.is_admin()
        assert org_tab_live._users_roles._admin_widget.isHidden()


# ---------------------------------------------------------------------------
# Refresh Behavior Tests
# ---------------------------------------------------------------------------

class TestRefreshBehavior:

    def test_refresh_button_enabled_after_probe(self, org_tab, api_client):
        """Refresh button is re-enabled after probe completes."""
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()):
            org_tab.probe_and_refresh()

        assert org_tab._refresh_btn.isEnabled()
        assert org_tab._refresh_btn.text() == "Refresh"

    def test_refresh_button_enabled_after_probe_failure(self, org_tab, api_client):
        """Refresh button is re-enabled even if probe raises."""
        with patch.object(api_client, "probe_endpoint",
                          side_effect=Exception("network error")):
            try:
                org_tab.probe_and_refresh()
            except Exception:
                pass

        assert org_tab._refresh_btn.isEnabled()

    def test_on_refresh_invalidates_then_reprobes(self, org_tab, api_client):
        """_on_refresh() invalidates cache before re-probing."""
        # First populate
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()):
            org_tab.probe_and_refresh()

        assert org_tab._caps.is_available("users")

        # Now refresh with everything NOT_SUPPORTED
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.NOT_SUPPORTED, status_code=404)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab._on_refresh()

        assert not org_tab._caps.is_available("users")

    def test_unreachable_startup_state_schedules_auto_retry(self, org_tab, api_client):
        """Transient unreachable state should schedule a one-shot automatic retry."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()

        mock_single_shot.assert_called_once_with(org_tab.AUTO_RETRY_DELAY_MS, org_tab._auto_retry_probe)
        assert org_tab._auto_retry_scheduled is True

    def test_auto_retry_reprobes_and_recovers_content(self, org_tab, api_client):
        """Automatic retry should invalidate cached state and load content once the backend is ready."""
        probe_results = [
            ProbeResult(status=CapabilityStatus.UNREACHABLE),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={"permissions": ["system.admin"]}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={"permissions": ["system.admin"]}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
            ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200),
        ]

        with patch.object(api_client, "probe_endpoint", side_effect=probe_results), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot"):
            org_tab.probe_and_refresh()
            assert org_tab._outer_stack.currentWidget() == org_tab._placeholder
            org_tab._auto_retry_probe()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
        assert org_tab._auto_retry_scheduled is False

    def test_manual_refresh_cancels_scheduled_auto_retry(self, org_tab, api_client):
        """Manual refresh should clear any pending auto-retry marker before reprobe."""
        org_tab._auto_retry_scheduled = True

        with patch.object(org_tab._caps, "invalidate") as mock_invalidate, \
             patch.object(org_tab, "probe_and_refresh") as mock_probe:
            org_tab._on_refresh()

        assert org_tab._auto_retry_scheduled is False
        mock_invalidate.assert_called_once_with()
        mock_probe.assert_called_once_with()


# ---------------------------------------------------------------------------
# State Transition Tests
# ---------------------------------------------------------------------------

class TestStateTransitions:
    """Test transitions between visibility states."""

    def test_transition_from_gated_to_available(self, org_tab, api_client):
        """Tab transitions from gated → full panels when server becomes available."""
        # Start: community, unreachable
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=False):
            org_tab.probe_and_refresh()
        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

        # Transition: server comes up
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=False):
            org_tab.on_settings_changed()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

    def test_transition_from_available_to_auth_failure(self, org_tab, api_client):
        """Tab transitions from full panels → auth message when key becomes invalid."""
        # Start: all available
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

        # Transition: key revoked
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.on_settings_changed()
        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_transition_from_auth_failure_to_available(self, org_tab, api_client):
        """Tab transitions from auth failure → full panels when key is fixed."""
        # Start: all unauthorized
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=401)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()
        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

        # Transition: key fixed
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.on_settings_changed()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page


class TestServerOffline:
    """Test show_server_offline() for no-backend scenario."""

    def test_show_server_offline_displays_placeholder(self, org_tab):
        """show_server_offline() should switch to the placeholder with a clear message."""
        org_tab.show_server_offline()
        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

    def test_show_server_offline_does_not_overwrite_loaded_content(self, org_tab, api_client):
        """If tab already has real content, show_server_offline() should not overwrite it."""
        # First: load real content
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

        # Now: health check says offline — should NOT revert to placeholder
        org_tab.show_server_offline()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

    def test_show_server_offline_then_api_ready_loads_content(self, org_tab, api_client):
        """After showing offline, probe_and_refresh should recover normally."""
        org_tab.show_server_offline()
        assert org_tab._outer_stack.currentWidget() == org_tab._placeholder

        # Server comes up
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()
        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
