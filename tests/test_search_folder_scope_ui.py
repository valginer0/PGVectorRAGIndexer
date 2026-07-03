"""Desktop UI tests for folder search scope (include/exclude chips).

Covers:
- SearchTab scope state: add/remove/clear, include<->exclude flips, dedupe
- Chip row visibility and chip-click removal
- perform_search passes path_prefixes / excluded_path_prefixes to SearchWorker
- DocumentsTab.search_scope_requested signal payloads
"""

import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from desktop_app.ui.search_tab import SearchTab
from desktop_app.ui.documents_tab import DocumentsTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_api_client():
    client = MagicMock()
    client.is_api_available.return_value = True
    client.get_health.return_value = {"status": "ok"}
    client.get_metadata_keys.return_value = []
    client.get_metadata_values.return_value = []
    return client


@pytest.fixture
def search_tab(qapp, mock_api_client):
    tab = SearchTab(mock_api_client, source_manager=MagicMock())
    tab.show()
    return tab


class TestScopeState:
    def test_no_scope_by_default(self, search_tab):
        assert search_tab.scope_filters() is None
        assert not search_tab.scope_group.isVisible()

    def test_add_include(self, search_tab):
        search_tab.add_scope_include("C:/Docs/Legal")
        assert search_tab.scope_filters() == {"path_prefixes": ["C:/Docs/Legal"]}
        assert search_tab.scope_group.isVisible()

    def test_add_exclude(self, search_tab):
        search_tab.add_scope_exclude("C:/Docs/Archive")
        assert search_tab.scope_filters() == {
            "excluded_path_prefixes": ["C:/Docs/Archive"]
        }

    def test_include_and_exclude_combined(self, search_tab):
        search_tab.add_scope_include("C:/Docs")
        search_tab.add_scope_exclude("C:/Docs/old")
        assert search_tab.scope_filters() == {
            "path_prefixes": ["C:/Docs"],
            "excluded_path_prefixes": ["C:/Docs/old"],
        }

    def test_duplicate_include_ignored(self, search_tab):
        search_tab.add_scope_include("C:/Docs")
        search_tab.add_scope_include("C:/Docs")
        assert search_tab.scope_filters() == {"path_prefixes": ["C:/Docs"]}

    def test_trailing_slash_normalized(self, search_tab):
        search_tab.add_scope_include("C:/Docs/")
        search_tab.add_scope_include("C:/Docs")
        assert search_tab.scope_filters() == {"path_prefixes": ["C:/Docs"]}

    def test_exclude_flips_existing_include(self, search_tab):
        search_tab.add_scope_include("C:/Docs")
        search_tab.add_scope_exclude("C:/Docs")
        assert search_tab.scope_filters() == {
            "excluded_path_prefixes": ["C:/Docs"]
        }

    def test_include_flips_existing_exclude(self, search_tab):
        search_tab.add_scope_exclude("C:/Docs")
        search_tab.add_scope_include("C:/Docs")
        assert search_tab.scope_filters() == {"path_prefixes": ["C:/Docs"]}

    def test_clear_scope(self, search_tab):
        search_tab.add_scope_include("A")
        search_tab.add_scope_exclude("B")
        search_tab.clear_scope()
        assert search_tab.scope_filters() is None
        assert not search_tab.scope_group.isVisible()

    def test_empty_path_ignored(self, search_tab):
        search_tab.add_scope_include("")
        search_tab.add_scope_include("/")
        assert search_tab.scope_filters() is None


class TestScopeChips:
    def _chips(self, search_tab):
        layout = search_tab._scope_chip_layout
        return [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if layout.itemAt(i).widget() is not None
        ]

    def test_one_chip_per_entry(self, search_tab):
        search_tab.add_scope_include("C:/Docs/Legal")
        search_tab.add_scope_exclude("C:/Docs/Archive")
        chips = self._chips(search_tab)
        assert len(chips) == 2
        texts = [c.text() for c in chips]
        assert any("Legal" in t and "not" not in t for t in texts)
        assert any("not Archive" in t for t in texts)

    def test_chip_tooltip_has_full_path(self, search_tab):
        search_tab.add_scope_include("C:/Docs/Legal")
        chip = self._chips(search_tab)[0]
        assert "C:/Docs/Legal" in chip.toolTip()

    def test_chip_click_removes_entry(self, search_tab):
        search_tab.add_scope_include("C:/Docs/Legal")
        search_tab.add_scope_exclude("C:/Docs/Archive")
        include_chip = self._chips(search_tab)[0]
        include_chip.click()
        assert search_tab.scope_filters() == {
            "excluded_path_prefixes": ["C:/Docs/Archive"]
        }


class TestScopeInSearch:
    def test_perform_search_passes_scope_filters(self, search_tab):
        search_tab.query_input.setText("contract terms")
        search_tab.add_scope_include("C:/Docs/Legal")
        search_tab.add_scope_exclude("C:/Docs/Legal/old")

        with patch("desktop_app.ui.search_tab.SearchWorker") as MockWorker:
            search_tab.perform_search()
            MockWorker.assert_called_once()
            kwargs = MockWorker.call_args.kwargs
            assert kwargs["filters"] == {
                "path_prefixes": ["C:/Docs/Legal"],
                "excluded_path_prefixes": ["C:/Docs/Legal/old"],
            }

    def test_perform_search_without_scope_passes_none(self, search_tab):
        search_tab.query_input.setText("contract terms")

        with patch("desktop_app.ui.search_tab.SearchWorker") as MockWorker:
            search_tab.perform_search()
            assert MockWorker.call_args.kwargs["filters"] is None


class TestDocumentsTabScopeSignal:
    def test_signal_payloads(self, qapp, mock_api_client):
        tab = DocumentsTab(mock_api_client)
        received = []
        tab.search_scope_requested.connect(
            lambda path, mode: received.append((path, mode))
        )
        tab.search_scope_requested.emit("C:/Docs/Legal", "include")
        tab.search_scope_requested.emit("C:/Docs/Archive", "exclude")
        assert received == [
            ("C:/Docs/Legal", "include"),
            ("C:/Docs/Archive", "exclude"),
        ]
