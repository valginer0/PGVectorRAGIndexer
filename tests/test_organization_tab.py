"""Automated QA tests for the Organization tab, settings integration, and widget-level behavior.

Requires: pytest-qt, QT_QPA_PLATFORM=offscreen (set in conftest or environment).
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Force offscreen rendering before any Qt import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_app.utils.api_client import APIClient, CapabilityStatus, ProbeResult
from desktop_app.ui.styles.theme import Theme
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
        _ApiKeysPanel, _ScimPanel,
    )
    with patch.object(_OverviewPanel, "refresh", _noop_refresh), \
         patch.object(_UsersRolesPanel, "refresh", _noop_refresh), \
         patch.object(_PermissionsPanel, "refresh", _noop_refresh), \
         patch.object(_RetentionPanel, "refresh", _noop_refresh), \
         patch.object(_ActivityPanel, "refresh", _noop_refresh), \
         patch.object(_ApiKeysPanel, "refresh", _noop_refresh), \
         patch.object(_ScimPanel, "refresh", _noop_refresh), \
         patch.object(api_client._base, "request", return_value=MagicMock()):
        tab = OrganizationTab(api_client)
        yield tab
    tab.deleteLater()


@pytest.fixture
def org_tab_live(qapp, api_client):
    """OrganizationTab WITHOUT mocked panel refreshes — for testing real panel behavior.
    Tests using this must mock the individual API calls themselves."""
    from desktop_app.ui.admin_tab import OrganizationTab
    with patch.object(api_client._base, "request", return_value=MagicMock()):
        tab = OrganizationTab(api_client)
        yield tab
    tab.deleteLater()


@pytest.fixture(autouse=True)
def suppress_qt_single_shot_timers():
    """Prevent real Qt timer callbacks from running in ordinary state-machine tests."""
    with patch("desktop_app.ui.admin_tab.QTimer.singleShot"):
        yield


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
        assert org_tab._sub_tabs.count() == 8  # Overview + 7 sub-tabs

        # Second: only users available
        status_map = {k: CapabilityStatus.NOT_SUPPORTED for k in _PROBES}
        status_map["me"] = CapabilityStatus.AVAILABLE
        status_map["users"] = CapabilityStatus.AVAILABLE
        with patch.object(api_client, "probe_endpoint",
                          side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab._on_refresh()

        assert org_tab._sub_tabs.count() == 4  # Overview + Users & Roles + Licenses + SCIM


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
             patch.object(api_client, "list_keys", return_value={"keys": []}), \
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
        assert not org_tab_live._users_roles._add_user_btn.isHidden()
        assert not org_tab_live._retention._run_section.isHidden()  # available to any authenticated user
        assert not org_tab_live._api_keys._create_btn.isHidden()  # admin has keys.manage implicitly

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
             patch.object(api_client, "list_keys", return_value={"keys": []}), \
             patch.object(api_client, "get_retention_policy", return_value={}), \
             patch.object(api_client, "get_retention_status", return_value={}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": [], "total": 0}), \
             patch.object(api_client, "get_activity_action_types", return_value={"action_types": []}), \
             patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            org_tab_live.probe_and_refresh()

        assert not org_tab_live._caps.is_admin()
        assert org_tab_live._users_roles._admin_widget.isHidden()
        # Retention run is available to any authenticated user (not admin-only)
        assert not org_tab_live._retention._run_section.isHidden()
        # keys.manage permission not granted → create button hidden
        assert org_tab_live._api_keys._create_btn.isHidden()


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
        """Transient unreachable state should schedule an automatic retry."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()

        mock_single_shot.assert_called_once_with(org_tab.AUTO_RETRY_DELAY_MS, org_tab._auto_retry_probe)
        assert org_tab._auto_retry_scheduled is True
        assert org_tab._auto_retry_attempts == 1
        assert org_tab._transient_retry_window_active is True

    def test_edition_denial_startup_state_schedules_auto_retry(self, org_tab, api_client):
        """LIC_3006 during startup should also schedule an automatic retry."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=403, error_code="LIC_3006")), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()

        mock_single_shot.assert_called_once_with(org_tab.AUTO_RETRY_DELAY_MS, org_tab._auto_retry_probe)
        assert org_tab._auto_retry_scheduled is True
        assert org_tab._auto_retry_attempts == 1
        assert org_tab._transient_retry_window_active is True

    def test_auto_retry_reprobes_and_recovers_content(self, org_tab, api_client):
        """Automatic retry should invalidate cached state and load content once the backend is ready."""
        num_probes = len(_PROBES)
        probe_results = (
            [ProbeResult(status=CapabilityStatus.UNREACHABLE)] * num_probes
            + [ProbeResult(status=CapabilityStatus.AVAILABLE, body={"permissions": ["system.admin"]}, status_code=200)]
            + [ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)] * (num_probes - 1)
        )

        with patch.object(api_client, "probe_endpoint", side_effect=probe_results), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot"):
            org_tab.probe_and_refresh()
            assert org_tab._outer_stack.currentWidget() == org_tab._placeholder
            org_tab._auto_retry_probe()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
        assert org_tab._auto_retry_scheduled is False
        assert org_tab._auto_retry_attempts == 0
        assert org_tab._transient_retry_window_active is False

    def test_auto_retry_reschedules_until_retry_budget_exhausted(self, org_tab, api_client):
        """Transient startup failures should keep retrying up to the configured retry budget."""
        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNREACHABLE)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()

            for attempt in range(2, org_tab.MAX_AUTO_RETRY_ATTEMPTS + 1):
                org_tab._auto_retry_probe()
                assert org_tab._auto_retry_attempts == attempt

            org_tab._auto_retry_probe()

        # One singleShot per retry attempt (no extra deferred call — terminal
        # state is now handled directly in _update_visibility)
        assert mock_single_shot.call_count == org_tab.MAX_AUTO_RETRY_ATTEMPTS
        assert org_tab._auto_retry_scheduled is False
        assert org_tab._auto_retry_attempts == org_tab.MAX_AUTO_RETRY_ATTEMPTS
        assert org_tab._transient_retry_window_active is False

    def test_backend_healthy_reprobes_placeholder_and_recovers_content(self, org_tab, api_client):
        """A later backend-healthy signal should reprobe transient placeholder state and load content."""
        num_probes = len(_PROBES)
        probe_results = (
            [ProbeResult(status=CapabilityStatus.UNREACHABLE)] * num_probes
            + [ProbeResult(status=CapabilityStatus.AVAILABLE, body={"permissions": ["system.admin"]}, status_code=200)]
            + [ProbeResult(status=CapabilityStatus.AVAILABLE, body={}, status_code=200)] * (num_probes - 1)
        )

        with patch.object(api_client, "probe_endpoint", side_effect=probe_results), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()
            assert org_tab._outer_stack.currentWidget() == org_tab._placeholder
            assert org_tab._awaiting_backend_healthy_reprobe is True

            org_tab._auto_retry_scheduled = False
            mock_single_shot.reset_mock()
            org_tab.on_backend_healthy()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page
        assert org_tab._awaiting_backend_healthy_reprobe is False
        assert org_tab._auto_retry_scheduled is False
        assert org_tab._auto_retry_attempts == 0
        mock_single_shot.assert_not_called()

    def test_backend_healthy_does_not_overwrite_loaded_content(self, org_tab, api_client):
        """A later backend-healthy signal should do nothing once real content is already loaded."""
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        assert org_tab._outer_stack.currentWidget() == org_tab._tabs_page

        with patch.object(org_tab, "probe_and_refresh") as mock_probe:
            org_tab.on_backend_healthy()

        mock_probe.assert_not_called()

    def test_steady_state_edition_denial_does_not_schedule_auto_retry(self, org_tab, api_client):
        """Stable edition denial outside the transient startup window should not auto-retry."""
        org_tab._transient_retry_window_active = False

        with patch.object(api_client, "probe_endpoint",
                          return_value=ProbeResult(status=CapabilityStatus.UNAUTHORIZED, status_code=403, error_code="LIC_3006")), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot") as mock_single_shot:
            org_tab.probe_and_refresh()

        mock_single_shot.assert_not_called()
        assert org_tab._auto_retry_scheduled is False
        assert org_tab._auto_retry_attempts == 0

    def test_manual_refresh_cancels_scheduled_auto_retry(self, org_tab, api_client):
        """Manual refresh should clear any pending auto-retry marker before reprobe."""
        org_tab._auto_retry_scheduled = True
        org_tab._auto_retry_attempts = 2
        org_tab._transient_retry_window_active = True

        with patch.object(org_tab._caps, "invalidate") as mock_invalidate, \
             patch.object(org_tab, "probe_and_refresh") as mock_probe:
            org_tab._on_refresh()

        assert org_tab._auto_retry_scheduled is False
        assert org_tab._auto_retry_attempts == 0
        assert org_tab._transient_retry_window_active is False
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


# ---------------------------------------------------------------------------
# API Keys Panel Tests
# ---------------------------------------------------------------------------

class TestHasPermission:
    """Tests for ServerCapabilities.has_permission()."""

    def test_admin_has_all_permissions(self, caps):
        caps._me_response = {"permissions": ["system.admin"]}
        assert caps.has_permission("keys.manage")
        assert caps.has_permission("docs.read")
        assert caps.has_permission("anything.at.all")

    def test_specific_permission_check(self, caps):
        caps._me_response = {"permissions": ["keys.manage", "docs.read"]}
        assert caps.has_permission("keys.manage")
        assert caps.has_permission("docs.read")
        assert not caps.has_permission("system.admin")
        assert not caps.has_permission("users.delete")

    def test_no_me_response(self, caps):
        caps._me_response = None
        assert not caps.has_permission("keys.manage")

    def test_is_admin_uses_has_permission(self, caps):
        caps._me_response = {"permissions": ["system.admin"]}
        assert caps.is_admin()
        caps._me_response = {"permissions": ["keys.manage"]}
        assert not caps.is_admin()


class TestApiKeysPanel:
    """Tests for the _ApiKeysPanel sub-tab."""

    def test_keys_panel_shows_keys(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _ApiKeysPanel(api_client, caps)

        keys_data = {"keys": [
            {"id": 1, "name": "CI Key", "prefix": "pgv_sk_abc", "created_at": "2025-01-01T00:00:00Z",
             "last_used_at": "2025-06-01T00:00:00Z", "status": "active"},
            {"id": 2, "name": "Old Key", "prefix": "pgv_sk_def", "created_at": "2024-01-01T00:00:00Z",
             "last_used_at": None, "status": "revoked"},
        ]}
        with patch.object(api_client, "list_keys", return_value=keys_data):
            panel.refresh()

        assert panel._table.rowCount() == 2
        assert panel._table.item(0, 0).text() == "CI Key"
        assert panel._table.item(0, 4).text() == "Active"
        assert panel._table.item(1, 4).text() == "Revoked"
        assert not panel._create_btn.isHidden()
        panel.deleteLater()

    def test_keys_panel_shows_create_for_keys_manage_permission(self, qapp, api_client):
        """Non-admin user with keys.manage permission should see Create button."""
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["keys.manage"]}
        panel = _ApiKeysPanel(api_client, caps)

        with patch.object(api_client, "list_keys", return_value={"keys": []}):
            panel.refresh()

        assert not panel._create_btn.isHidden()
        panel.deleteLater()

    def test_keys_panel_hides_create_without_permission(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _ApiKeysPanel(api_client, caps)

        with patch.object(api_client, "list_keys", return_value={"keys": []}):
            panel.refresh()

        assert panel._create_btn.isHidden()
        panel.deleteLater()

    def test_keys_panel_not_supported(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.NOT_SUPPORTED
        panel = _ApiKeysPanel(api_client, caps)
        panel.refresh()
        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Retention Run Now Tests
# ---------------------------------------------------------------------------

class TestRetentionRunNow:
    """Tests for the retention Run Now controls."""

    def test_run_section_visible_for_authenticated_user(self, qapp, api_client):
        """Backend requires API key + Team edition, not admin — so any authenticated user sees Run Now."""
        from desktop_app.ui.admin_tab import _RetentionPanel
        caps = ServerCapabilities(api_client)
        caps._cache["retention"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _RetentionPanel(api_client, caps)

        with patch.object(api_client, "get_retention_policy", return_value={"policy": {}}), \
             patch.object(api_client, "get_retention_status", return_value={}):
            panel.refresh()

        assert not panel._run_section.isHidden()
        panel.deleteLater()

    def test_run_section_hidden_when_not_available(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _RetentionPanel
        caps = ServerCapabilities(api_client)
        caps._cache["retention"] = CapabilityStatus.NOT_SUPPORTED
        panel = _RetentionPanel(api_client, caps)
        panel.refresh()
        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()


# ---------------------------------------------------------------------------
# SCIM Panel Tests
# ---------------------------------------------------------------------------

class TestScimPanel:
    """Tests for the _ScimPanel sub-tab."""

    def test_scim_panel_shows_status(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}

        with patch.object(api_client._base, "request", return_value=mock_response), \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            panel.refresh()

        assert panel._stack.currentWidget() == panel._content
        assert "scim/v2/Users" in panel._scim_endpoint.text()
        panel.deleteLater()

    def test_scim_panel_not_enabled(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.NOT_SUPPORTED
        panel = _ScimPanel(api_client, caps)
        panel.refresh()
        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()

    def test_scim_panel_shows_provisioning_events(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        entries = [
            {"ts": "2025-06-01T10:00:00Z", "action": "user.scim_provisioned", "user_id": "u1", "details": {"email": "a@b.com"}},
            {"ts": "2025-06-01T11:00:00Z", "action": "user.login", "user_id": "u2", "details": None},
            {"ts": "2025-06-01T12:00:00Z", "action": "user.scim_deprovisioned", "user_id": "u3", "details": None},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        with patch.object(api_client._base, "request", return_value=mock_response), \
             patch.object(api_client, "get_activity_log", return_value={"entries": entries}):
            panel.refresh()

        # Only SCIM events should appear (2 of 3)
        assert panel._events_table.rowCount() == 2
        assert panel._events_table.item(0, 1).text() == "user.scim_provisioned"
        assert panel._events_table.item(1, 1).text() == "user.scim_deprovisioned"
        panel.deleteLater()


# ---------------------------------------------------------------------------
# User Management Write Operations Tests
# ---------------------------------------------------------------------------

class TestUserManagementOps:
    """Tests for user add/delete/activate/deactivate controls."""

    def test_add_user_button_visible_for_admin(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _UsersRolesPanel
        caps = ServerCapabilities(api_client)
        caps._cache["users"] = CapabilityStatus.AVAILABLE
        caps._cache["roles"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _UsersRolesPanel(api_client, caps)

        with patch.object(api_client, "list_users", return_value={"users": []}), \
             patch.object(api_client, "list_roles", return_value={"roles": [{"name": "user", "description": "", "permissions": []}]}):
            panel.refresh()

        assert not panel._admin_widget.isHidden()
        assert not panel._add_user_btn.isHidden()
        panel.deleteLater()

    def test_context_menu_policy_set(self, qapp, api_client):
        """Users table should have custom context menu policy."""
        from desktop_app.ui.admin_tab import _UsersRolesPanel
        from PySide6.QtCore import Qt
        caps = ServerCapabilities(api_client)
        panel = _UsersRolesPanel(api_client, caps)
        assert panel._users_table.contextMenuPolicy() == Qt.CustomContextMenu
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Compliance Export Tests
# ---------------------------------------------------------------------------

class TestComplianceExport:
    """Tests for the compliance export button in Overview."""

    def test_export_button_visible_for_admin(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _OverviewPanel
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        assert not panel._export_widget.isHidden()
        panel.deleteLater()

    def test_export_button_hidden_for_non_admin(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _OverviewPanel
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        assert panel._export_widget.isHidden()
        panel.deleteLater()

    def test_export_compliance_success(self, qapp, api_client):
        """Export compliance report saves ZIP file when admin clicks export."""
        from desktop_app.ui.admin_tab import _OverviewPanel
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        zip_data = b"PK\x03\x04fake_zip_content"
        with patch.object(api_client, "export_compliance_report", return_value=zip_data), \
             patch("desktop_app.ui.admin_tab.QFileDialog.getSaveFileName", return_value=("/tmp/test_report.zip", "ZIP Files (*.zip)")), \
             patch("builtins.open", MagicMock()) as mock_open, \
             patch("desktop_app.ui.admin_tab.QMessageBox.information"):
            panel._on_export_compliance()

        mock_open.assert_called_once_with("/tmp/test_report.zip", "wb")
        panel.deleteLater()

    def test_export_compliance_cancel(self, qapp, api_client):
        """Cancelling file dialog does not write anything."""
        from desktop_app.ui.admin_tab import _OverviewPanel
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        with patch.object(api_client, "export_compliance_report", return_value=b"data"), \
             patch("desktop_app.ui.admin_tab.QFileDialog.getSaveFileName", return_value=("", "")), \
             patch("builtins.open") as mock_open:
            panel._on_export_compliance()

        mock_open.assert_not_called()
        panel.deleteLater()

    def test_export_compliance_auth_error(self, qapp, api_client):
        """Auth error during export shows warning dialog."""
        from desktop_app.ui.admin_tab import _OverviewPanel
        from desktop_app.utils.errors import APIAuthenticationError
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        with patch.object(api_client, "export_compliance_report", side_effect=APIAuthenticationError("forbidden")), \
             patch("desktop_app.ui.admin_tab.QMessageBox.warning") as mock_warn:
            panel._on_export_compliance()

        mock_warn.assert_called_once()
        assert "Admin" in mock_warn.call_args[0][2]
        panel.deleteLater()

    def test_export_compliance_api_error(self, qapp, api_client):
        """Generic API error during export shows warning dialog."""
        from desktop_app.ui.admin_tab import _OverviewPanel
        from desktop_app.utils.errors import APIError
        caps = ServerCapabilities(api_client)
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        with patch.object(api_client, "export_compliance_report", side_effect=APIError("server timeout")), \
             patch("desktop_app.ui.admin_tab.QMessageBox.warning") as mock_warn:
            panel._on_export_compliance()

        mock_warn.assert_called_once()
        assert "server timeout" in mock_warn.call_args[0][2]
        panel.deleteLater()


# ---------------------------------------------------------------------------
# User Management — Full Write Operation Tests
# ---------------------------------------------------------------------------

class TestUserCreateFlow:
    """Tests for the Add User dialog and create_user API call."""

    @pytest.fixture
    def admin_users_panel(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _UsersRolesPanel
        caps = ServerCapabilities(api_client)
        caps._cache["users"] = CapabilityStatus.AVAILABLE
        caps._cache["roles"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _UsersRolesPanel(api_client, caps)
        with patch.object(api_client, "list_users", return_value={"users": [
            {"id": "u1", "email": "existing@test.com", "display_name": "Existing", "role": "user", "is_active": True, "last_login_at": None, "auth_provider": "local"}
        ]}), \
             patch.object(api_client, "list_roles", return_value={"roles": [
                 {"name": "admin", "description": "Admin", "permissions": ["system.admin"]},
                 {"name": "user", "description": "User", "permissions": ["docs.read"]},
             ]}):
            panel.refresh()
        yield panel
        panel.deleteLater()

    def test_create_user_success(self, admin_users_panel, api_client):
        """Creating a user calls create_user and refreshes the table."""
        panel = admin_users_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=1), \
             patch("desktop_app.ui.admin_tab.QLineEdit.text", side_effect=["new@test.com", "New User", "new@test.com", "New User"]), \
             patch.object(api_client, "create_user", return_value={"id": "u2"}) as mock_create, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._on_add_user()

        mock_create.assert_called_once()
        mock_refresh.assert_called_once()

    def test_create_user_cancelled(self, admin_users_panel, api_client):
        """Cancelling the dialog does not call create_user."""
        panel = admin_users_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=0), \
             patch.object(api_client, "create_user") as mock_create:
            panel._on_add_user()

        mock_create.assert_not_called()

    def test_create_user_auth_error(self, admin_users_panel, api_client):
        """Auth error shows message panel with warning."""
        from desktop_app.utils.errors import APIAuthenticationError
        panel = admin_users_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=1), \
             patch("desktop_app.ui.admin_tab.QLineEdit.text", side_effect=["fail@test.com", "Fail", "fail@test.com", "Fail"]), \
             patch.object(api_client, "create_user", side_effect=APIAuthenticationError("forbidden")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._on_add_user()

        mock_msg.assert_called_once()
        assert "Admin" in mock_msg.call_args[0][0]

    def test_create_user_api_error(self, admin_users_panel, api_client):
        """Generic API error shows error message."""
        from desktop_app.utils.errors import APIError
        panel = admin_users_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=1), \
             patch("desktop_app.ui.admin_tab.QLineEdit.text", side_effect=["dup@test.com", "Dup", "dup@test.com", "Dup"]), \
             patch.object(api_client, "create_user", side_effect=APIError("email already exists")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._on_add_user()

        mock_msg.assert_called_once()
        assert "error" == mock_msg.call_args[1].get("icon")


class TestUserActivateDeactivateDelete:
    """Tests for activate/deactivate/delete user operations."""

    @pytest.fixture
    def panel_with_users(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _UsersRolesPanel
        caps = ServerCapabilities(api_client)
        caps._cache["users"] = CapabilityStatus.AVAILABLE
        caps._cache["roles"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _UsersRolesPanel(api_client, caps)
        users = [
            {"id": "u1", "email": "active@test.com", "display_name": "Active", "role": "user", "is_active": True, "last_login_at": None, "auth_provider": "local"},
            {"id": "u2", "email": "inactive@test.com", "display_name": "Inactive", "role": "user", "is_active": False, "last_login_at": None, "auth_provider": "local"},
        ]
        with patch.object(api_client, "list_users", return_value={"users": users}), \
             patch.object(api_client, "list_roles", return_value={"roles": [{"name": "user", "description": "", "permissions": []}]}):
            panel.refresh()
        yield panel
        panel.deleteLater()

    def test_deactivate_user_confirmed(self, panel_with_users, api_client):
        """Confirming deactivation calls update_user and refreshes."""
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "update_user", return_value={}) as mock_update, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._toggle_user_active("u1", "active@test.com", False)

        mock_update.assert_called_once_with("u1", is_active=False)
        mock_refresh.assert_called_once()

    def test_activate_user_confirmed(self, panel_with_users, api_client):
        """Confirming activation calls update_user with is_active=True."""
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "update_user", return_value={}) as mock_update, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._toggle_user_active("u2", "inactive@test.com", True)

        mock_update.assert_called_once_with("u2", is_active=True)
        mock_refresh.assert_called_once()

    def test_deactivate_user_cancelled(self, panel_with_users, api_client):
        """Cancelling deactivation does not call update_user."""
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.No), \
             patch.object(api_client, "update_user") as mock_update:
            panel._toggle_user_active("u1", "active@test.com", False)

        mock_update.assert_not_called()

    def test_delete_user_confirmed(self, panel_with_users, api_client):
        """Confirming delete calls delete_user and refreshes."""
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.Yes), \
             patch.object(api_client, "delete_user", return_value={}) as mock_delete, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._delete_user("u1", "active@test.com")

        mock_delete.assert_called_once_with("u1")
        mock_refresh.assert_called_once()

    def test_delete_user_cancelled(self, panel_with_users, api_client):
        """Cancelling delete does not call delete_user."""
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.No), \
             patch.object(api_client, "delete_user") as mock_delete:
            panel._delete_user("u1", "active@test.com")

        mock_delete.assert_not_called()

    def test_delete_user_auth_error(self, panel_with_users, api_client):
        """Auth error on delete shows warning message."""
        from desktop_app.utils.errors import APIAuthenticationError
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.Yes), \
             patch.object(api_client, "delete_user", side_effect=APIAuthenticationError("forbidden")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._delete_user("u1", "active@test.com")

        mock_msg.assert_called_once()
        assert "Admin" in mock_msg.call_args[0][0]

    def test_deactivate_user_api_error(self, panel_with_users, api_client):
        """API error on deactivation shows error message with action verb."""
        from desktop_app.utils.errors import APIError
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "update_user", side_effect=APIError("server error")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._toggle_user_active("u1", "active@test.com", False)

        mock_msg.assert_called_once()
        assert "deactivate" in mock_msg.call_args[0][0]

    def test_activate_user_api_error(self, panel_with_users, api_client):
        """API error on activation shows error message with action verb."""
        from desktop_app.utils.errors import APIError
        panel = panel_with_users
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "update_user", side_effect=APIError("server error")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._toggle_user_active("u2", "inactive@test.com", True)

        mock_msg.assert_called_once()
        assert "activate" in mock_msg.call_args[0][0]

    def test_users_table_displays_active_status_colors(self, panel_with_users):
        """Active=Yes should be green, Active=No should be red."""
        from PySide6.QtGui import QColor
        panel = panel_with_users
        active_item = panel._users_table.item(0, 3)
        inactive_item = panel._users_table.item(1, 3)
        assert active_item.text() == "Yes"
        assert inactive_item.text() == "No"
        assert active_item.foreground().color() == QColor(Theme.SUCCESS)
        assert inactive_item.foreground().color() == QColor(Theme.ERROR)

    def test_user_id_stored_in_item_data(self, panel_with_users):
        """Each row stores the user_id in Qt.UserRole on the first column."""
        from PySide6.QtCore import Qt
        panel = panel_with_users
        assert panel._users_table.item(0, 0).data(Qt.UserRole) == "u1"
        assert panel._users_table.item(1, 0).data(Qt.UserRole) == "u2"

    def test_context_menu_blocked_for_non_admin(self, qapp, api_client):
        """Non-admin user cannot trigger context menu actions."""
        from PySide6.QtCore import QPoint
        from desktop_app.ui.admin_tab import _UsersRolesPanel
        caps = ServerCapabilities(api_client)
        caps._cache["users"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _UsersRolesPanel(api_client, caps)

        with patch.object(api_client, "list_users", return_value={"users": [
            {"id": "u1", "email": "a@b.com", "display_name": "A", "role": "user", "is_active": True, "last_login_at": None, "auth_provider": "local"}
        ]}), \
             patch.object(api_client, "list_roles", return_value={"roles": []}):
            panel.refresh()

        with patch("desktop_app.ui.admin_tab.QMenu") as mock_menu:
            panel._on_users_context_menu(QPoint(10, 10))

        mock_menu.assert_not_called()
        panel.deleteLater()


# ---------------------------------------------------------------------------
# API Keys — Full Write Operation Tests
# ---------------------------------------------------------------------------

class TestApiKeyCreateFlow:
    """Tests for the Create Key dialog and key display."""

    @pytest.fixture
    def admin_keys_panel(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _ApiKeysPanel(api_client, caps)
        with patch.object(api_client, "list_keys", return_value={"keys": []}):
            panel.refresh()
        yield panel
        panel.deleteLater()

    def test_create_key_success_shows_key_dialog(self, admin_keys_panel, api_client):
        """Successful key creation shows the key in a dialog with copy button."""
        panel = admin_keys_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", side_effect=[1, 1]), \
             patch("desktop_app.ui.admin_tab.QLineEdit.text", side_effect=["CI Pipeline", "CI Pipeline"]), \
             patch.object(api_client, "create_key", return_value={"key": "pgv_sk_abc123xyz"}) as mock_create, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._on_create_key()

        mock_create.assert_called_once_with("CI Pipeline")
        mock_refresh.assert_called_once()

    def test_create_key_cancelled(self, admin_keys_panel, api_client):
        """Cancelling the dialog does not call create_key."""
        panel = admin_keys_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=0), \
             patch.object(api_client, "create_key") as mock_create:
            panel._on_create_key()

        mock_create.assert_not_called()

    def test_create_key_auth_error(self, admin_keys_panel, api_client):
        """Auth error shows permission-specific message."""
        from desktop_app.utils.errors import APIAuthenticationError
        panel = admin_keys_panel
        with patch("desktop_app.ui.admin_tab.QDialog.exec", return_value=1), \
             patch("desktop_app.ui.admin_tab.QLineEdit.text", side_effect=["Test", "Test"]), \
             patch.object(api_client, "create_key", side_effect=APIAuthenticationError("forbidden")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._on_create_key()

        mock_msg.assert_called_once()
        assert "keys.manage" in mock_msg.call_args[0][0]


class TestApiKeyRevokeRotate:
    """Tests for revoke and rotate key operations via extracted _revoke_key/_rotate_key methods."""

    @pytest.fixture
    def keys_panel_with_data(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["keys.manage"]}
        panel = _ApiKeysPanel(api_client, caps)
        keys_data = {"keys": [
            {"id": 1, "name": "Active Key", "prefix": "pgv_sk_abc", "created_at": "2025-01-01T00:00:00Z", "last_used_at": None, "status": "active"},
            {"id": 2, "name": "Revoked Key", "prefix": "pgv_sk_def", "created_at": "2024-01-01T00:00:00Z", "last_used_at": None, "status": "revoked"},
        ]}
        with patch.object(api_client, "list_keys", return_value=keys_data):
            panel.refresh()
        yield panel
        panel.deleteLater()

    def test_revoke_key_confirmed(self, keys_panel_with_data, api_client):
        """Confirming revoke calls revoke_key API and refreshes the panel."""
        panel = keys_panel_with_data
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.Yes), \
             patch.object(api_client, "revoke_key", return_value={}) as mock_revoke, \
             patch.object(panel, "refresh") as mock_refresh:
            panel._revoke_key(1, "Active Key")

        mock_revoke.assert_called_once_with(1)
        mock_refresh.assert_called_once()

    def test_revoke_key_cancelled(self, keys_panel_with_data, api_client):
        """Cancelling revoke does not call revoke_key API."""
        panel = keys_panel_with_data
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.No), \
             patch.object(api_client, "revoke_key") as mock_revoke:
            panel._revoke_key(1, "Active Key")

        mock_revoke.assert_not_called()

    def test_revoke_key_api_error(self, keys_panel_with_data, api_client):
        """API error during revoke shows error message via panel._show_message."""
        from desktop_app.utils.errors import APIError
        panel = keys_panel_with_data
        with patch("desktop_app.ui.admin_tab.QMessageBox.warning", return_value=QMessageBox.Yes), \
             patch.object(api_client, "revoke_key", side_effect=APIError("server error")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._revoke_key(1, "Active Key")

        mock_msg.assert_called_once()
        assert "revoke" in mock_msg.call_args[0][0].lower()
        assert mock_msg.call_args[1]["icon"] == "error"

    def test_rotate_key_confirmed(self, keys_panel_with_data, api_client):
        """Confirming rotate calls rotate_key API, shows new key in dialog, and refreshes."""
        from PySide6.QtWidgets import QLineEdit as _QLineEdit
        panel = keys_panel_with_data
        shown_keys = []

        def capture_exec(self_dialog):
            # Find the read-only QLineEdit inside the key dialog
            for child in self_dialog.findChildren(_QLineEdit):
                if child.isReadOnly():
                    shown_keys.append(child.text())
            return 1

        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "rotate_key", return_value={"key": "pgv_sk_new123"}) as mock_rotate, \
             patch.object(panel, "refresh") as mock_refresh:
            # Patch exec on QDialog instances so we can inspect the dialog content
            from desktop_app.ui.admin_tab import QDialog
            with patch.object(QDialog, "exec", capture_exec):
                panel._rotate_key(1, "Active Key")

        mock_rotate.assert_called_once_with(1)
        mock_refresh.assert_called_once()
        assert shown_keys == ["pgv_sk_new123"]

    def test_rotate_key_cancelled(self, keys_panel_with_data, api_client):
        """Cancelling rotate does not call rotate_key API."""
        panel = keys_panel_with_data
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.No), \
             patch.object(api_client, "rotate_key") as mock_rotate:
            panel._rotate_key(1, "Active Key")

        mock_rotate.assert_not_called()

    def test_rotate_key_api_error(self, keys_panel_with_data, api_client):
        """API error during rotate shows error message via panel._show_message."""
        from desktop_app.utils.errors import APIError
        panel = keys_panel_with_data
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "rotate_key", side_effect=APIError("timeout")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._rotate_key(1, "Active Key")

        mock_msg.assert_called_once()
        assert "rotate" in mock_msg.call_args[0][0].lower()
        assert mock_msg.call_args[1]["icon"] == "error"

    def test_keys_table_status_colors(self, keys_panel_with_data):
        """Active keys should be green, revoked keys should be red."""
        from PySide6.QtGui import QColor
        panel = keys_panel_with_data
        active_status = panel._table.item(0, 4)
        revoked_status = panel._table.item(1, 4)
        assert active_status.text() == "Active"
        assert revoked_status.text() == "Revoked"
        assert active_status.foreground().color() == QColor(Theme.SUCCESS)
        assert revoked_status.foreground().color() == QColor(Theme.ERROR)

    def test_key_id_stored_in_item_data(self, keys_panel_with_data):
        """Each row stores the key ID in Qt.UserRole."""
        from PySide6.QtCore import Qt
        panel = keys_panel_with_data
        assert panel._table.item(0, 0).data(Qt.UserRole) == 1
        assert panel._table.item(1, 0).data(Qt.UserRole) == 2

    def test_keys_panel_connection_error(self, qapp, api_client):
        """Connection error during refresh shows retry message."""
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        from desktop_app.utils.errors import APIConnectionError
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["keys.manage"]}
        panel = _ApiKeysPanel(api_client, caps)

        with patch.object(api_client, "list_keys", side_effect=APIConnectionError("timeout")):
            panel.refresh()

        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()

    def test_keys_panel_auth_error(self, qapp, api_client):
        """Auth error during refresh shows warning message."""
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        from desktop_app.utils.errors import APIAuthenticationError
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["keys.manage"]}
        panel = _ApiKeysPanel(api_client, caps)

        with patch.object(api_client, "list_keys", side_effect=APIAuthenticationError("unauthorized")):
            panel.refresh()

        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()

    def test_context_menu_blocked_without_keys_manage(self, qapp, api_client):
        """User without keys.manage permission cannot use context menu."""
        from PySide6.QtCore import QPoint
        from desktop_app.ui.admin_tab import _ApiKeysPanel
        caps = ServerCapabilities(api_client)
        caps._cache["keys"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _ApiKeysPanel(api_client, caps)

        with patch.object(api_client, "list_keys", return_value={"keys": [
            {"id": 1, "name": "Key", "prefix": "pgv_sk_a", "created_at": None, "last_used_at": None, "status": "active"}
        ]}):
            panel.refresh()

        with patch("desktop_app.ui.admin_tab.QMenu") as mock_menu:
            panel._on_context_menu(QPoint(10, 10))

        mock_menu.assert_not_called()
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Retention Run Now — Full Operation Tests
# ---------------------------------------------------------------------------

class TestRetentionRunNowFlow:
    """Tests for the Run Now button interaction."""

    @pytest.fixture
    def retention_panel(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _RetentionPanel
        caps = ServerCapabilities(api_client)
        caps._cache["retention"] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["docs.read"]}
        panel = _RetentionPanel(api_client, caps)
        with patch.object(api_client, "get_retention_policy", return_value={"policy": {
            "activity_days": 90, "indexing_runs_days": 365, "quarantine_days": 30, "cleanup_saml_sessions": True
        }}), \
             patch.object(api_client, "get_retention_status", return_value={
                 "enabled": True, "last_run_at": "2025-06-01T00:00:00Z", "next_run_at": "2025-06-02T00:00:00Z", "status": "idle"
             }):
            panel.refresh()
        yield panel
        panel.deleteLater()

    def test_retention_policy_displayed(self, retention_panel):
        """Policy values are correctly displayed."""
        panel = retention_panel
        assert "90" in panel._activity_days.text()
        assert "365" in panel._runs_days.text()
        assert "30" in panel._quarantine_days.text()
        assert panel._saml_cleanup.text() == "Yes"

    def test_retention_status_displayed(self, retention_panel):
        """Execution status values are correctly displayed."""
        panel = retention_panel
        assert panel._ret_enabled.text() == "Yes"
        assert "2025-06-01" in panel._last_run.text()
        assert panel._run_status.text() == "idle"

    def test_run_now_confirmed_success(self, retention_panel, api_client):
        """Confirming Run Now calls run_retention with the spinbox values."""
        panel = retention_panel
        panel._run_activity.setValue(30)
        panel._run_quarantine.setValue(7)
        panel._run_indexing.setValue(0)
        panel._run_saml.setChecked(False)

        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "run_retention", return_value={"removed": {"activity_log": 5, "quarantine": 2}}) as mock_run, \
             patch.object(panel, "_show_message") as mock_msg, \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot"):
            panel._on_run_retention()

        mock_run.assert_called_once_with(
            activity_days=30, quarantine_days=7, cleanup_saml_sessions=False
        )
        mock_msg.assert_called_once()
        assert "activity_log: 5" in mock_msg.call_args[0][0]

    def test_run_now_with_defaults(self, retention_panel, api_client):
        """Spinboxes at 0 ('Use default') are not passed to the API."""
        panel = retention_panel
        panel._run_activity.setValue(0)
        panel._run_quarantine.setValue(0)
        panel._run_indexing.setValue(0)
        panel._run_saml.setChecked(True)

        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "run_retention", return_value={"removed": {}}) as mock_run, \
             patch.object(panel, "_show_message"), \
             patch("desktop_app.ui.admin_tab.QTimer.singleShot"):
            panel._on_run_retention()

        mock_run.assert_called_once_with(cleanup_saml_sessions=True)

    def test_run_now_cancelled(self, retention_panel, api_client):
        """Cancelling Run Now does not call the API."""
        panel = retention_panel
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.No), \
             patch.object(api_client, "run_retention") as mock_run:
            panel._on_run_retention()

        mock_run.assert_not_called()

    def test_run_now_auth_error(self, retention_panel, api_client):
        """Auth error shows permission message (not 'Admin required')."""
        from desktop_app.utils.errors import APIAuthenticationError
        panel = retention_panel
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "run_retention", side_effect=APIAuthenticationError("forbidden")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._on_run_retention()

        mock_msg.assert_called_once()
        assert "Insufficient permissions" in mock_msg.call_args[0][0]
        assert "Admin" not in mock_msg.call_args[0][0]

    def test_run_now_api_error(self, retention_panel, api_client):
        """Generic API error shows error message."""
        from desktop_app.utils.errors import APIError
        panel = retention_panel
        with patch("desktop_app.ui.admin_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "run_retention", side_effect=APIError("timeout")), \
             patch.object(panel, "_show_message") as mock_msg:
            panel._on_run_retention()

        mock_msg.assert_called_once()
        assert "error" == mock_msg.call_args[1].get("icon")

    def test_retention_connection_error(self, qapp, api_client):
        """Connection error during policy fetch shows retry."""
        from desktop_app.ui.admin_tab import _RetentionPanel
        from desktop_app.utils.errors import APIConnectionError
        caps = ServerCapabilities(api_client)
        caps._cache["retention"] = CapabilityStatus.AVAILABLE
        panel = _RetentionPanel(api_client, caps)

        with patch.object(api_client, "get_retention_policy", side_effect=APIConnectionError("timeout")):
            panel.refresh()

        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()

    def test_retention_unauthorized(self, qapp, api_client):
        """Unauthorized capability shows auth message without attempting API call."""
        from desktop_app.ui.admin_tab import _RetentionPanel
        caps = ServerCapabilities(api_client)
        caps._cache["retention"] = CapabilityStatus.UNAUTHORIZED
        panel = _RetentionPanel(api_client, caps)
        panel.refresh()
        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()


# ---------------------------------------------------------------------------
# SCIM Panel — Full Data Display Tests
# ---------------------------------------------------------------------------

class TestScimPanelData:
    """Tests for SCIM panel data display and edge cases."""

    def test_scim_endpoint_url_construction(self, qapp, api_client):
        """Endpoint URL is correctly derived from the base URL."""
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "researcher"}
        with patch.object(api_client._base, "request", return_value=mock_response), \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            panel.refresh()

        assert panel._scim_endpoint.text().endswith("/scim/v2/Users")
        assert panel._scim_default_role.text() == "researcher"
        panel.deleteLater()

    def test_scim_config_fetch_failure_fallback(self, qapp, api_client):
        """Config fetch failure falls back to 'Yes (config unavailable)' and '—' default role."""
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        with patch.object(api_client._base, "request", side_effect=Exception("timeout")), \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            panel.refresh()

        assert panel._scim_enabled.text() == "Yes (config unavailable)"
        assert panel._scim_default_role.text() == "—"
        assert panel._scim_endpoint.text() != ""
        assert panel._stack.currentWidget() == panel._content
        panel.deleteLater()

    def test_scim_activity_log_error(self, qapp, api_client):
        """Activity log fetch failure results in empty events table, not crash."""
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        mock_response = MagicMock()
        mock_response.json.return_value = {}
        with patch.object(api_client._base, "request", return_value=mock_response), \
             patch.object(api_client, "get_activity_log", side_effect=Exception("error")):
            panel.refresh()

        assert panel._events_table.rowCount() == 0
        panel.deleteLater()

    def test_scim_filters_only_scim_events(self, qapp, api_client):
        """Only user.scim_* events appear; other events are filtered out."""
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.AVAILABLE
        panel = _ScimPanel(api_client, caps)

        entries = [
            {"ts": "2025-06-01T10:00:00Z", "action": "user.scim_provisioned", "user_id": "u1", "details": None},
            {"ts": "2025-06-01T11:00:00Z", "action": "user.login", "user_id": "u2", "details": None},
            {"ts": "2025-06-01T12:00:00Z", "action": "document.indexed", "user_id": None, "details": None},
            {"ts": "2025-06-01T13:00:00Z", "action": "user.scim_updated", "user_id": "u3", "details": None},
            {"ts": "2025-06-01T14:00:00Z", "action": "user.scim_patched", "user_id": "u4", "details": None},
            {"ts": "2025-06-01T15:00:00Z", "action": "user.scim_deprovisioned", "user_id": "u5", "details": None},
            {"ts": "2025-06-01T16:00:00Z", "action": "user.created", "user_id": "u6", "details": None},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        with patch.object(api_client._base, "request", return_value=mock_response), \
             patch.object(api_client, "get_activity_log", return_value={"entries": entries}):
            panel.refresh()

        assert panel._events_table.rowCount() == 4
        actions = [panel._events_table.item(i, 1).text() for i in range(4)]
        assert actions == [
            "user.scim_provisioned", "user.scim_updated",
            "user.scim_patched", "user.scim_deprovisioned"
        ]
        panel.deleteLater()

    def test_scim_unreachable(self, qapp, api_client):
        """Unreachable SCIM shows retry message."""
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        caps._cache["scim"] = CapabilityStatus.UNREACHABLE
        panel = _ScimPanel(api_client, caps)
        panel.refresh()
        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Full Tab Integration — Sub-tab Wiring Tests
# ---------------------------------------------------------------------------

class TestSubTabWiring:
    """Tests that new sub-tabs are correctly wired into OrganizationTab."""

    def test_api_keys_tab_appears_when_available(self, org_tab, api_client):
        """API Keys tab appears when keys capability is available."""
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "API Keys" in tab_titles

    def test_scim_tab_appears_when_available(self, org_tab, api_client):
        """SCIM tab appears when scim capability is available."""
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "SCIM" in tab_titles

    def test_api_keys_tab_hidden_when_not_supported(self, org_tab, api_client):
        """API Keys tab does not appear when keys capability is NOT_SUPPORTED."""
        status_map = {k: CapabilityStatus.AVAILABLE for k in _PROBES}
        status_map["keys"] = CapabilityStatus.NOT_SUPPORTED
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "API Keys" not in tab_titles

    def test_scim_tab_always_visible(self, org_tab, api_client):
        """SCIM tab is always shown — displays setup guide when not enabled."""
        status_map = {k: CapabilityStatus.AVAILABLE for k in _PROBES}
        status_map["scim"] = CapabilityStatus.NOT_SUPPORTED
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert "SCIM" in tab_titles

    def test_tab_order(self, org_tab, api_client):
        """Sub-tabs appear in the correct order."""
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn()), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert tab_titles == ["Overview", "Users & Roles", "Permissions", "API Keys", "Licenses", "Retention", "Activity", "SCIM"]

    def test_only_keys_and_scim_available(self, org_tab, api_client):
        """Tab shows only the sub-tabs whose capabilities are available."""
        status_map = {k: CapabilityStatus.NOT_SUPPORTED for k in _PROBES}
        status_map["me"] = CapabilityStatus.AVAILABLE
        status_map["keys"] = CapabilityStatus.AVAILABLE
        status_map["scim"] = CapabilityStatus.AVAILABLE
        with patch.object(api_client, "probe_endpoint", side_effect=_make_probe_fn(status_map)), \
             patch("desktop_app.utils.edition.is_feature_available", return_value=True):
            org_tab.probe_and_refresh()

        tab_titles = [org_tab._sub_tabs.tabText(i) for i in range(org_tab._sub_tabs.count())]
        assert tab_titles == ["Overview", "API Keys", "Licenses", "SCIM"]


# ---------------------------------------------------------------------------
# Overview Panel — Data Display Tests
# ---------------------------------------------------------------------------

class TestOverviewPanelData:
    """Tests for the Overview panel data display."""

    def test_overview_shows_capability_count(self, qapp, api_client):
        """Overview panel shows all probed capabilities (excluding 'me')."""
        from desktop_app.ui.admin_tab import _OverviewPanel
        from desktop_app.utils.server_capabilities import _PROBES
        caps = ServerCapabilities(api_client)
        for name in _PROBES:
            caps._cache[name] = CapabilityStatus.AVAILABLE
        caps._me_response = {"permissions": ["system.admin"]}
        panel = _OverviewPanel(api_client, caps)

        with patch("desktop_app.utils.app_config.is_remote_mode", return_value=False), \
             patch("desktop_app.utils.edition.get_edition_display", return_value=MagicMock(edition_label="Team")):
            panel.refresh()

        expected_rows = len([k for k in _PROBES if k != "me"])
        assert panel._cap_table.rowCount() == expected_rows
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Permissions Panel — Mapping and Error Tests
# ---------------------------------------------------------------------------

class TestPermissionsPanelBehavior:
    """Tests for the Permissions panel."""

    def test_permissions_sorted_by_category(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _PermissionsPanel
        caps = ServerCapabilities(api_client)
        caps._cache["permissions"] = CapabilityStatus.AVAILABLE
        panel = _PermissionsPanel(api_client, caps)

        perms = [
            {"permission": "users.manage", "description": "Manage users"},
            {"permission": "docs.read", "description": "Read docs"},
            {"permission": "docs.write", "description": "Write docs"},
            {"permission": "audit.view", "description": "View audit"},
        ]
        with patch.object(api_client, "list_permissions", return_value={"permissions": perms}):
            panel.refresh()

        categories = [panel._table.item(i, 2).text() for i in range(panel._table.rowCount())]
        assert categories == sorted(categories)
        panel.deleteLater()

    def test_permissions_connection_error_shows_retry(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _PermissionsPanel
        from desktop_app.utils.errors import APIConnectionError
        caps = ServerCapabilities(api_client)
        caps._cache["permissions"] = CapabilityStatus.AVAILABLE
        panel = _PermissionsPanel(api_client, caps)

        with patch.object(api_client, "list_permissions", side_effect=APIConnectionError("timeout")):
            panel.refresh()

        assert panel._stack.currentWidget() == panel._msg_page
        panel.deleteLater()


# ---------------------------------------------------------------------------
# Activity Panel — Tests
# ---------------------------------------------------------------------------

class TestActivityPanelBehavior:
    """Tests for the Activity panel."""

    def test_activity_loads_entries(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ActivityPanel
        caps = ServerCapabilities(api_client)
        caps._cache["activity"] = CapabilityStatus.AVAILABLE
        panel = _ActivityPanel(api_client, caps)

        entries = [
            {"ts": "2025-06-01T10:00:00Z", "action": "user.login", "client_id": "c1", "user_id": "u1", "details": {"ip": "1.2.3.4"}},
            {"ts": "2025-06-01T11:00:00Z", "action": "document.indexed", "client_id": None, "user_id": None, "details": None},
        ]
        with patch.object(api_client, "get_activity_action_types", return_value={"actions": ["user.login", "document.indexed"]}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": entries}):
            panel.refresh()

        assert panel._table.rowCount() == 2
        assert panel._table.item(0, 1).text() == "user.login"
        assert panel._table.item(1, 2).text() == "—"  # null client_id → "—"
        panel.deleteLater()

    def test_activity_load_more(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ActivityPanel
        caps = ServerCapabilities(api_client)
        caps._cache["activity"] = CapabilityStatus.AVAILABLE
        panel = _ActivityPanel(api_client, caps)

        page1 = [{"ts": f"2025-06-01T{i:02d}:00:00Z", "action": "test", "client_id": None, "user_id": None, "details": None} for i in range(100)]
        page2 = [{"ts": "2025-06-02T00:00:00Z", "action": "test", "client_id": None, "user_id": None, "details": None}]

        with patch.object(api_client, "get_activity_action_types", return_value={"actions": []}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": page1}):
            panel.refresh()

        assert panel._table.rowCount() == 100
        assert not panel._load_more_btn.isHidden()

        with patch.object(api_client, "get_activity_log", return_value={"entries": page2}):
            panel._load_more()

        assert panel._table.rowCount() == 101
        assert panel._load_more_btn.isHidden()  # < 100 results → hide button
        panel.deleteLater()

    def test_activity_truncates_long_details(self, qapp, api_client):
        from desktop_app.ui.admin_tab import _ActivityPanel
        caps = ServerCapabilities(api_client)
        caps._cache["activity"] = CapabilityStatus.AVAILABLE
        panel = _ActivityPanel(api_client, caps)

        entries = [{"ts": "2025-06-01T00:00:00Z", "action": "test", "client_id": None, "user_id": None, "details": {"data": "x" * 200}}]
        with patch.object(api_client, "get_activity_action_types", return_value={"actions": []}), \
             patch.object(api_client, "get_activity_log", return_value={"entries": entries}):
            panel.refresh()

        detail_text = panel._table.item(0, 4).text()
        assert len(detail_text) <= 103  # 100 chars + "..."
        assert detail_text.endswith("...")
        panel.deleteLater()


# ---------------------------------------------------------------------------
# SCIM Panel — Group Management & Admin Gating Tests
# ---------------------------------------------------------------------------

class TestScimGroupManagement:
    """Tests for SCIM group-to-role mapping UI and admin gating."""

    def _make_scim_panel(self, qapp, api_client, is_admin=True):
        from desktop_app.ui.admin_tab import _ScimPanel
        caps = ServerCapabilities(api_client)
        for name in _PROBES:
            caps._cache[name] = CapabilityStatus.AVAILABLE
        if is_admin:
            caps._me_response = {"permissions": ["system.admin"]}
        else:
            caps._me_response = {"permissions": ["docs.read"]}
        return _ScimPanel(api_client, caps), caps

    def test_add_group_button_visible_for_admin(self, qapp, api_client):
        """Admin user sees 'Add Group Mapping' button."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()
        # Use isHidden() — isVisible() returns False in offscreen mode
        assert not panel._group_btn_row.isHidden()
        panel.deleteLater()

    def test_add_group_button_hidden_for_non_admin(self, qapp, api_client):
        """Non-admin user does not see 'Add Group Mapping' button."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()
        assert panel._group_btn_row.isHidden()
        panel.deleteLater()

    def test_context_menu_blocked_for_non_admin(self, qapp, api_client):
        """Non-admin right-click on groups table does nothing (no menu)."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()
        # Simulate right-click — should return early without showing menu
        from PySide6.QtCore import QPoint
        with patch("PySide6.QtWidgets.QMenu.exec") as mock_menu:
            panel._on_group_context_menu(QPoint(10, 10))
            mock_menu.assert_not_called()
        panel.deleteLater()

    def test_groups_table_populated(self, qapp, api_client):
        """Groups table loads data from the admin endpoint."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        config_resp = MagicMock()
        config_resp.json.return_value = {"defaultRole": "user"}
        groups_resp = MagicMock()
        groups_resp.json.return_value = {
            "groups": [
                {"id": "g1", "display_name": "Admins", "role_name": "admin",
                 "member_count": 3, "created_at": "2026-01-01T00:00:00+00:00"},
                {"id": "g2", "display_name": "Users", "role_name": "user",
                 "member_count": 10, "created_at": "2026-01-02T00:00:00+00:00"},
            ],
            "total": 2,
        }
        def side_effect(method, url, **kwargs):
            if "scim-groups" in url:
                return groups_resp
            return config_resp
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.side_effect = side_effect
            panel.refresh()
        assert panel._groups_table.rowCount() == 2
        assert panel._groups_table.item(0, 0).text() == "Admins"
        assert panel._groups_table.item(0, 1).text() == "admin"
        assert panel._groups_table.item(1, 0).text() == "Users"
        panel.deleteLater()

    def test_add_group_dialog_validation(self, qapp, api_client):
        """Add Group dialog rejects empty group name with a warning."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()

        from PySide6.QtWidgets import QDialog
        with patch.object(QDialog, "exec", return_value=QDialog.Accepted), \
             patch.object(api_client, "list_roles", return_value={"roles": [{"name": "admin"}]}), \
             patch.object(QMessageBox, "warning") as mock_warn:
            panel._on_add_group()
            # Empty name → validation warning, no POST
            mock_warn.assert_called_once()
            assert "required" in str(mock_warn.call_args).lower()
        panel.deleteLater()

    def test_add_group_dialog_cancel(self, qapp, api_client):
        """Cancelling the add group dialog does not send any request."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()

        from PySide6.QtWidgets import QDialog
        with patch.object(QDialog, "exec", return_value=QDialog.Rejected), \
             patch.object(api_client, "list_roles", return_value={"roles": [{"name": "admin"}]}), \
             patch.object(api_client, "_base") as mock_base:
            panel._on_add_group()
            # Cancelled → no request made
            mock_base.request.assert_not_called()
        panel.deleteLater()

    def test_setup_guide_has_open_button(self, qapp, api_client):
        """Setup guide panel includes 'Open Full Setup Guide' button."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        caps._cache["scim"] = CapabilityStatus.NOT_SUPPORTED
        panel.refresh()
        from PySide6.QtWidgets import QPushButton
        buttons = panel._msg_page.findChildren(QPushButton)
        button_texts = [b.text() for b in buttons]
        assert any("Setup Guide" in t for t in button_texts), f"Expected setup guide button, found: {button_texts}"
        panel.deleteLater()

    def test_open_setup_guide_calls_system_open(self, qapp, api_client):
        """Open Full Setup Guide button triggers system file opener."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        caps._cache["scim"] = CapabilityStatus.NOT_SUPPORTED
        panel.refresh()
        
        # Patch both possible openers to be platform-agnostic
        with patch("subprocess.Popen") as mock_popen, \
             patch("os.startfile", create=True) as mock_startfile, \
             patch("pathlib.Path.exists", return_value=True):
            panel._open_setup_guide_file()
            
            import sys
            if sys.platform == "win32":
                mock_startfile.assert_called_once()
                assert "SCIM_SETUP.md" in str(mock_startfile.call_args[0][0])
            else:
                mock_popen.assert_called_once()
                call_args = mock_popen.call_args[0][0]
                assert any("SCIM_SETUP.md" in str(a) for a in call_args)
        panel.deleteLater()

    def test_open_setup_guide_missing_file(self, qapp, api_client):
        """Open guide shows warning when file doesn't exist."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        caps._cache["scim"] = CapabilityStatus.NOT_SUPPORTED
        panel.refresh()
        with patch("pathlib.Path.exists", return_value=False), \
             patch.object(QMessageBox, "warning") as mock_warn:
            panel._open_setup_guide_file()
            mock_warn.assert_called_once()
        panel.deleteLater()

    def test_events_include_group_actions(self, qapp, api_client):
        """Provisioning events table includes group.scim_* events."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        entries = [
            {"ts": "2026-01-01T00:00:00Z", "action": "group.scim_created", "user_id": None, "details": {"group_id": "g1"}},
            {"ts": "2026-01-01T01:00:00Z", "action": "user.scim_provisioned", "user_id": "u1", "details": {}},
        ]
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": entries}):
            mock_base.request.return_value = mock_response
            panel.refresh()
        assert panel._events_table.rowCount() == 2
        actions = [panel._events_table.item(i, 1).text() for i in range(2)]
        assert "group.scim_created" in actions
        assert "user.scim_provisioned" in actions
        panel.deleteLater()

    def test_add_group_successful_post(self, qapp, api_client):
        """Successful add group sends POST with correct display_name and role_name."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"defaultRole": "user"}
        with patch.object(api_client, "_base") as mock_base, \
             patch.object(api_client, "get_activity_log", return_value={"entries": []}):
            mock_base.request.return_value = mock_response
            panel.refresh()

        from PySide6.QtWidgets import QDialog, QLineEdit
        # Patch exec to accept, and inject text into the QLineEdit before it returns
        original_exec = QDialog.exec
        def fake_exec(dlg):
            # Find the QLineEdit in the dialog and set text
            line_edits = dlg.findChildren(QLineEdit)
            if line_edits:
                line_edits[0].setText("Engineering Admins")
            return QDialog.Accepted
        with patch.object(QDialog, "exec", fake_exec), \
             patch.object(api_client, "list_roles", return_value={"roles": [{"name": "admin"}, {"name": "user"}]}), \
             patch.object(api_client, "_base") as mock_base, \
             patch.object(panel, "refresh"):
            mock_base.request.return_value = mock_response
            panel._on_add_group()
            mock_base.request.assert_called_once_with(
                "POST",
                f"{api_client.base_url}/scim-groups",
                json={"display_name": "Engineering Admins", "role_name": "admin"},
            )
        panel.deleteLater()

    def _setup_groups_table_for_delete(self, panel):
        """Helper: populate groups table with one row for delete tests."""
        from PySide6.QtCore import Qt as QtCore_Qt
        from PySide6.QtWidgets import QTableWidgetItem
        panel._groups_table.setRowCount(1)
        name_item = QTableWidgetItem("Admins")
        name_item.setData(QtCore_Qt.UserRole, "g1")
        panel._groups_table.setItem(0, 0, name_item)
        panel._groups_table.setItem(0, 1, QTableWidgetItem("admin"))

    def test_delete_group_confirmed(self, qapp, api_client):
        """Confirmed delete sends DELETE /scim-groups/{id} and refreshes."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        self._setup_groups_table_for_delete(panel)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(api_client, "_base") as mock_base, \
             patch.object(panel, "refresh") as mock_refresh:
            mock_base.request.return_value = MagicMock()
            panel._confirm_delete_group("g1", "Admins")
            mock_base.request.assert_called_once_with(
                "DELETE",
                f"{api_client.base_url}/scim-groups/g1",
            )
            mock_refresh.assert_called_once()
        panel.deleteLater()

    def test_delete_group_cancelled(self, qapp, api_client):
        """Cancelled delete confirmation does not send DELETE request."""
        panel, caps = self._make_scim_panel(qapp, api_client, is_admin=True)
        self._setup_groups_table_for_delete(panel)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.No), \
             patch.object(api_client, "_base") as mock_base:
            panel._confirm_delete_group("g1", "Admins")
            mock_base.request.assert_not_called()
        panel.deleteLater()
