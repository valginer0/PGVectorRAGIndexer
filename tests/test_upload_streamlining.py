"""
Tests for #5 Upload Tab UI Streamlining.

Tests cover:
- Folder button is primary (has 'primary' class property)
- Files button is secondary (smaller, subdued)
- Last indexed label exists and is hidden by default
- _update_last_indexed method exists and handles errors gracefully
- Button order: folder before files in layout
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.slow


# ===========================================================================
# Test: Upload tab structure (requires PySide6)
# ===========================================================================


class TestUploadTabStreamlining:
    @pytest.fixture(autouse=True)
    def _setup_tab(self):
        """Create an UploadTab with a mocked API client."""
        from desktop_app.ui.upload_tab import UploadTab
        mock_api = MagicMock()
        mock_api.is_api_available.return_value = False
        self.tab = UploadTab(api_client=mock_api)

    def test_folder_button_is_primary(self):
        """The 'Index Folder' button should have the 'primary' class."""
        assert self.tab.select_folder_btn.property("class") == "primary"

    def test_folder_button_is_taller(self):
        """The folder button should be taller than the files button."""
        assert self.tab.select_folder_btn.minimumHeight() > self.tab.select_files_btn.minimumHeight()

    def test_folder_button_text(self):
        """The folder button should say 'Index Folder'."""
        assert "Index Folder" in self.tab.select_folder_btn.text()

    def test_files_button_text(self):
        """The files button should say 'Individual Files'."""
        assert "Individual Files" in self.tab.select_files_btn.text()

    def test_last_indexed_label_exists(self):
        """The last indexed label should exist."""
        assert hasattr(self.tab, "last_indexed_label")

    def test_last_indexed_label_hidden_by_default(self):
        """The last indexed label should be hidden initially."""
        assert not self.tab.last_indexed_label.isVisible()

    def test_update_last_indexed_method_exists(self):
        """The _update_last_indexed method should exist."""
        assert callable(getattr(self.tab, "_update_last_indexed", None))

    def test_update_last_indexed_handles_api_unavailable(self):
        """_update_last_indexed should not crash when API is unavailable."""
        self.tab.api_client.is_api_available.return_value = False
        self.tab._update_last_indexed("/some/folder")
        assert not self.tab.last_indexed_label.isVisible()

    def test_update_last_indexed_handles_exception(self):
        """_update_last_indexed should not crash on API errors."""
        self.tab.api_client.is_api_available.return_value = True
        self.tab.api_client.search_document_tree.side_effect = Exception("API error")
        self.tab._update_last_indexed("/some/folder")
        assert not self.tab.last_indexed_label.isVisible()

    def test_update_last_indexed_shows_timestamp(self):
        """_update_last_indexed should show timestamp when results exist."""
        self.tab.api_client.is_api_available.return_value = True
        self.tab.api_client.search_document_tree.return_value = {
            "results": [{"indexed_at": "2026-02-10T15:00:00.000Z", "source_uri": "/docs/test.pdf"}],
            "count": 1,
        }
        self.tab._update_last_indexed("/docs")
        assert self.tab.last_indexed_label.isVisible()
        assert "2026-02-10" in self.tab.last_indexed_label.text()

    def test_update_last_indexed_shows_not_indexed(self):
        """_update_last_indexed should show 'Not previously indexed' when no results."""
        self.tab.api_client.is_api_available.return_value = True
        self.tab.api_client.search_document_tree.return_value = {
            "results": [],
            "count": 0,
        }
        self.tab._update_last_indexed("/new/folder")
        assert self.tab.last_indexed_label.isVisible()
        assert "Not previously indexed" in self.tab.last_indexed_label.text()
