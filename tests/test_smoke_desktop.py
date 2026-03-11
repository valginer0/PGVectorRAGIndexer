"""Headless smoke tests for desktop app widget integration.

These tests instantiate real Qt widgets (offscreen) with mock API clients
to verify that key UI flows work end-to-end without crashing.
Covers: OrganizationTab offline/probe states, PermissionsPanel field mapping,
and DocumentsTab tree-signal isolation in list mode.
"""

import os
import sys

import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtGui import QIcon

# Force offscreen rendering before any Qt import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

@pytest.fixture(autouse=True)
def mock_qtawesome():
    """Mock qta.icon to prevent FontError in headless CI environments (Windows/macOS Actions)."""
    with patch("qtawesome.icon", return_value=QIcon()) as mock_icon:
        yield mock_icon

from PySide6.QtWidgets import QApplication

from desktop_app.utils.api_client import APIClient, CapabilityStatus, ProbeResult
from desktop_app.utils.server_capabilities import ServerCapabilities


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def mock_api_client():
    mock = MagicMock(spec=APIClient)
    mock.base_url = "http://mock:8000"
    mock.probe_endpoint.return_value = ProbeResult(
        status=CapabilityStatus.UNREACHABLE,
        body=None,
        error_message="mock unreachable",
        status_code=None,
    )
    return mock


# ---------------------------------------------------------------------------
# OrganizationTab smoke tests
# ---------------------------------------------------------------------------

class TestOrganizationTabSmoke:

    def test_instantiation(self, qapp, mock_api_client):
        from desktop_app.ui.admin_tab import OrganizationTab
        tab = OrganizationTab(mock_api_client)
        assert tab is not None

    def test_show_server_offline_no_crash(self, qapp, mock_api_client):
        from desktop_app.ui.admin_tab import OrganizationTab
        tab = OrganizationTab(mock_api_client)
        tab.show_server_offline()
        assert tab._outer_stack.currentWidget() == tab._placeholder

    def test_probe_and_refresh_all_unreachable(self, qapp, mock_api_client):
        from desktop_app.ui.admin_tab import OrganizationTab
        tab = OrganizationTab(mock_api_client)
        # Should not crash even when all endpoints are unreachable
        tab.probe_and_refresh()

    def test_show_server_offline_idempotent(self, qapp, mock_api_client):
        from desktop_app.ui.admin_tab import OrganizationTab
        tab = OrganizationTab(mock_api_client)
        tab.show_server_offline()
        tab.show_server_offline()
        tab.show_server_offline()
        assert tab._outer_stack.currentWidget() == tab._placeholder


# ---------------------------------------------------------------------------
# PermissionsPanel field mapping smoke test
# ---------------------------------------------------------------------------

class TestPermissionsPanelSmoke:

    def test_refresh_maps_server_response_correctly(self, qapp, mock_api_client):
        """PermissionsPanel should map 'permission' field (not 'id') and derive category."""
        from desktop_app.ui.admin_tab import _PermissionsPanel

        mock_api_client.list_permissions.return_value = {
            "permissions": [
                {"permission": "documents.read", "description": "Search and retrieve documents"},
                {"permission": "system.admin", "description": "Full system access"},
                {"permission": "documents.visibility.all", "description": "Manage any doc visibility"},
            ]
        }

        caps = ServerCapabilities(mock_api_client)
        caps._cache["permissions"] = CapabilityStatus.AVAILABLE

        panel = _PermissionsPanel(mock_api_client, caps)
        panel.refresh()

        table = panel._table
        assert table.rowCount() == 3

        # Collect all rows into a dict keyed by permission name
        rows = {}
        for i in range(table.rowCount()):
            perm = table.item(i, 0).text()
            desc = table.item(i, 1).text()
            cat = table.item(i, 2).text()
            rows[perm] = (desc, cat)

        assert "documents.read" in rows
        assert rows["documents.read"] == ("Search and retrieve documents", "documents")

        assert "system.admin" in rows
        assert rows["system.admin"] == ("Full system access", "system")

        # Multi-dot permission: category derived from rsplit(".", 1)
        assert "documents.visibility.all" in rows
        assert rows["documents.visibility.all"] == ("Manage any doc visibility", "documents.visibility")


# ---------------------------------------------------------------------------
# DocumentsTab tree-signal isolation smoke test
# ---------------------------------------------------------------------------

class TestDocumentsTabTreeSignalIsolation:

    def test_tree_signals_ignored_in_list_mode(self, qapp, mock_api_client):
        """Tree signal handlers should not update status_label when view mode is 'list'."""
        from desktop_app.ui.documents_tab import DocumentsTab

        tab = DocumentsTab(mock_api_client)
        assert tab._view_mode == "list"

        original_text = tab.status_label.text()

        tab._on_tree_loading("some/path")
        assert tab.status_label.text() == original_text

        tab._on_tree_loaded("some/path", 42)
        assert tab.status_label.text() == original_text

        tab._on_tree_load_failed("connection refused")
        assert tab.status_label.text() == original_text
