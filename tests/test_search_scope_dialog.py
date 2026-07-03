"""Tests for the tri-state folder scope dialog.

Covers:
- ScopeSelection: tri-state logic, boundary compilation, blocked toggles,
  subtree reset, seeding from an existing scope
- ScopeTreeModel: checkbox flags/state/setData over injected tree nodes
- SearchScopeDialog: empty-selection guard, mode switching
- SearchTab.open_scope_dialog applies the dialog result to the chips
"""

import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from desktop_app.ui.search_scope_dialog import (
    ScopeSelection, ScopeTreeModel, SearchScopeDialog,
)
from desktop_app.ui.document_tree_model import TreeNode, COL_NAME
from desktop_app.ui.search_tab import SearchTab


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
    client.get_document_tree.return_value = {
        "children": [], "total_folders": 0, "total_files": 0,
    }
    return client


# ===========================================================================
# ScopeSelection (pure logic)
# ===========================================================================


class TestScopeSelectionAllMode:
    def test_default_everything_included(self):
        sel = ScopeSelection()
        assert sel.effective("C:/Docs") is True
        assert sel.display_state("C:/Docs") == "checked"
        assert sel.compile() == ([], [])

    def test_uncheck_becomes_exclude(self):
        sel = ScopeSelection()
        ok, _ = sel.toggle("C:/Docs/Archive")
        assert ok
        assert sel.display_state("C:/Docs/Archive") == "unchecked"
        assert sel.compile() == ([], ["C:/Docs/Archive"])

    def test_ancestor_shows_partial(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs/Archive")
        assert sel.display_state("C:/Docs") == "partial"
        assert sel.display_state("C:/Docs/Active") == "checked"

    def test_retoggle_removes_override(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs/Archive")
        sel.toggle("C:/Docs/Archive")
        assert sel.compile() == ([], [])
        assert sel.overrides == {}

    def test_toggle_parent_resets_subtree(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs/Archive")            # exclude child
        sel.toggle("C:/Docs")                    # partial -> fully checked
        assert sel.compile() == ([], [])
        sel.toggle("C:/Docs")                    # checked -> excluded
        assert sel.compile() == ([], ["C:/Docs"])

    def test_include_under_exclude_blocked(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs")                    # exclude C:/Docs
        ok, message = sel.toggle("C:/Docs/Legal")
        assert not ok
        assert "C:/Docs" in message
        assert sel.compile() == ([], ["C:/Docs"])

    def test_reinclude_excluded_folder_itself_allowed(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs")
        ok, _ = sel.toggle("C:/Docs")            # toggling itself is fine
        assert ok
        assert sel.compile() == ([], [])

    def test_sibling_boundary_not_confused(self):
        sel = ScopeSelection()
        sel.toggle("C:/Docs")
        # C:/Docs2 is a sibling, not a child — unaffected by the exclude
        assert sel.effective("C:/Docs2") is True
        assert sel.display_state("C:/Docs2") == "checked"


class TestScopeSelectionSelectedMode:
    def test_default_nothing_included(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        assert sel.effective("C:/Docs") is False
        assert sel.is_empty_selection()

    def test_check_becomes_include(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        ok, _ = sel.toggle("C:/Docs/Legal")
        assert ok
        assert sel.compile() == (["C:/Docs/Legal"], [])
        assert not sel.is_empty_selection()

    def test_exclude_inside_include(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        sel.toggle("C:/Docs")                    # include
        sel.toggle("C:/Docs/old")                # exclude within include
        assert sel.compile() == (["C:/Docs"], ["C:/Docs/old"])

    def test_include_under_exclude_under_include_blocked(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        sel.toggle("C:/Docs")
        sel.toggle("C:/Docs/old")
        ok, message = sel.toggle("C:/Docs/old/keep")
        assert not ok
        assert "C:/Docs/old" in message

    def test_multiple_includes(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        sel.toggle("B")
        sel.toggle("A")
        assert sel.compile() == (["A", "B"], [])

    def test_partial_on_ancestor_of_include(self):
        sel = ScopeSelection(ScopeSelection.MODE_SELECTED)
        sel.toggle("C:/Docs/Legal")
        assert sel.display_state("C:/Docs") == "partial"


class TestScopeSelectionSeeding:
    def test_seed_excludes_only_round_trip(self):
        sel = ScopeSelection.from_scope([], ["C:/Docs/Archive"])
        assert sel.mode == ScopeSelection.MODE_ALL
        assert sel.compile() == ([], ["C:/Docs/Archive"])

    def test_seed_includes_round_trip(self):
        sel = ScopeSelection.from_scope(["C:/Docs"], ["C:/Docs/old"])
        assert sel.mode == ScopeSelection.MODE_SELECTED
        assert sel.compile() == (["C:/Docs"], ["C:/Docs/old"])

    def test_seed_empty_is_all_mode_no_overrides(self):
        sel = ScopeSelection.from_scope([], [])
        assert sel.mode == ScopeSelection.MODE_ALL
        assert sel.compile() == ([], [])

    def test_set_mode_clears_overrides(self):
        sel = ScopeSelection.from_scope([], ["C:/Docs"])
        sel.set_mode(ScopeSelection.MODE_SELECTED)
        assert sel.overrides == {}
        assert sel.compile() == ([], [])


# ===========================================================================
# ScopeTreeModel (checkboxes over injected nodes, no worker threads)
# ===========================================================================


def _model_with_folders(qapp, mock_api_client, selection):
    model = ScopeTreeModel(mock_api_client, selection, source="postgres")
    root = model._root
    docs = TreeNode("Docs", "C:/Docs", "folder", parent=root)
    docs.row = 0
    readme = TreeNode("readme.md", "C:/readme.md", "file", parent=root)
    readme.row = 1
    root.children = [docs, readme]
    root.is_fetched = True
    legal = TreeNode("Legal", "C:/Docs/Legal", "folder", parent=docs)
    legal.row = 0
    docs.children = [legal]
    docs.is_fetched = True
    return model


class TestScopeTreeModel:
    def test_folder_is_checkable_file_is_not(self, qapp, mock_api_client):
        model = _model_with_folders(qapp, mock_api_client, ScopeSelection())
        folder_idx = model.index(0, COL_NAME)
        file_idx = model.index(1, COL_NAME)
        assert model.flags(folder_idx) & Qt.ItemIsUserCheckable
        assert not (model.flags(file_idx) & Qt.ItemIsUserCheckable)
        assert model.data(file_idx, Qt.CheckStateRole) is None

    def test_default_checked_in_all_mode(self, qapp, mock_api_client):
        model = _model_with_folders(qapp, mock_api_client, ScopeSelection())
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.CheckStateRole) == Qt.Checked

    def test_setdata_toggles_and_parent_goes_partial(self, qapp, mock_api_client):
        model = _model_with_folders(qapp, mock_api_client, ScopeSelection())
        docs_idx = model.index(0, COL_NAME)
        legal_idx = model.index(0, COL_NAME, docs_idx)
        assert model.setData(legal_idx, Qt.Unchecked, Qt.CheckStateRole)
        assert model.data(legal_idx, Qt.CheckStateRole) == Qt.Unchecked
        assert model.data(docs_idx, Qt.CheckStateRole) == Qt.PartiallyChecked
        assert model.selection.compile() == ([], ["C:/Docs/Legal"])

    def test_blocked_toggle_emits_rejection(self, qapp, mock_api_client):
        model = _model_with_folders(qapp, mock_api_client, ScopeSelection())
        docs_idx = model.index(0, COL_NAME)
        legal_idx = model.index(0, COL_NAME, docs_idx)
        model.setData(docs_idx, Qt.Unchecked, Qt.CheckStateRole)  # exclude Docs

        rejections = []
        model.toggle_rejected.connect(rejections.append)
        assert not model.setData(legal_idx, Qt.Checked, Qt.CheckStateRole)
        assert len(rejections) == 1
        assert "C:/Docs" in rejections[0]


# ===========================================================================
# SearchScopeDialog
# ===========================================================================


class TestSearchScopeDialog:
    def test_empty_selected_mode_blocks_accept(self, qapp, mock_api_client):
        dialog = SearchScopeDialog(mock_api_client, includes=[], excludes=[])
        dialog._selected_radio.setChecked(True)
        dialog._accept_if_valid()
        assert dialog.result() != QDialog.Accepted
        assert "match nothing" in dialog.hint_label.text()

    def test_accept_with_excludes(self, qapp, mock_api_client):
        dialog = SearchScopeDialog(mock_api_client, includes=[], excludes=[])
        dialog.selection.toggle("C:/Docs/Archive")
        dialog._accept_if_valid()
        assert dialog.result() == QDialog.Accepted
        assert dialog.selected_scope() == ([], ["C:/Docs/Archive"])

    def test_seeded_from_existing_scope(self, qapp, mock_api_client):
        dialog = SearchScopeDialog(
            mock_api_client, includes=["C:/Docs"], excludes=["C:/Docs/old"]
        )
        assert dialog._selected_radio.isChecked()
        assert dialog.selected_scope() == (["C:/Docs"], ["C:/Docs/old"])

    def test_mode_switch_clears_decisions(self, qapp, mock_api_client):
        dialog = SearchScopeDialog(mock_api_client, includes=[], excludes=["C:/x"])
        assert dialog._all_radio.isChecked()
        dialog._selected_radio.setChecked(True)
        assert dialog.selection.overrides == {}


# ===========================================================================
# SearchTab integration
# ===========================================================================


class TestSearchTabScopeDialog:
    def test_dialog_result_applied_to_chips(self, qapp, mock_api_client):
        tab = SearchTab(mock_api_client, source_manager=MagicMock())
        tab.show()

        with patch(
            "desktop_app.ui.search_scope_dialog.SearchScopeDialog"
        ) as MockDialog:
            instance = MockDialog.return_value
            instance.exec.return_value = QDialog.Accepted
            instance.selected_scope.return_value = (
                ["C:/Docs/Legal"], ["C:/Docs/Legal/old"]
            )
            tab.open_scope_dialog()

        assert tab.scope_filters() == {
            "path_prefixes": ["C:/Docs/Legal"],
            "excluded_path_prefixes": ["C:/Docs/Legal/old"],
        }
        assert tab.scope_group.isVisible()

    def test_cancel_leaves_scope_unchanged(self, qapp, mock_api_client):
        tab = SearchTab(mock_api_client, source_manager=MagicMock())
        tab.show()
        tab.add_scope_include("C:/Keep")

        with patch(
            "desktop_app.ui.search_scope_dialog.SearchScopeDialog"
        ) as MockDialog:
            instance = MockDialog.return_value
            instance.exec.return_value = QDialog.Rejected
            tab.open_scope_dialog()

        assert tab.scope_filters() == {"path_prefixes": ["C:/Keep"]}
