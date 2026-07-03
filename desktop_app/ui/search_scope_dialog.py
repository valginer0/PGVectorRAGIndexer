"""Folder scope picker for search: tri-state checkbox tree over the document tree.

The dialog compiles checkbox state down to the minimal include/exclude prefix
lists understood by the search API (path_prefixes / excluded_path_prefixes).
Because excluded_path_prefixes always win server-side, re-including a folder
inside an excluded one is not expressible — ScopeSelection.toggle blocks it.
"""

import logging
from typing import Dict, List, Optional, Tuple

import qtawesome as qta
from PySide6.QtCore import Qt, QModelIndex, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QTreeView, QDialogButtonBox,
)

from .document_tree_model import DocumentTreeModel, COL_NAME

logger = logging.getLogger(__name__)


def _is_under(path: str, ancestor: str) -> bool:
    """True when path lies strictly below ancestor (folder-boundary aware)."""
    return path.startswith(ancestor + "/")


class ScopeSelection:
    """Tri-state folder selection compiling to include/exclude prefix lists.

    mode "all":      everything searched by default; unchecked folders are excludes.
    mode "selected": nothing searched by default; checked folders are includes,
                     and unchecked folders inside an include become excludes.

    overrides maps folder path -> bool (included?). Only boundary overrides are
    kept: toggling always clears descendant overrides first, and an override
    equal to its inherited state is dropped.
    """

    MODE_ALL = "all"
    MODE_SELECTED = "selected"

    def __init__(self, mode: str = MODE_ALL,
                 overrides: Optional[Dict[str, bool]] = None):
        self.mode = mode
        self.overrides: Dict[str, bool] = dict(overrides or {})

    # -- construction ---------------------------------------------------

    @classmethod
    def from_scope(cls, includes: List[str], excludes: List[str]) -> "ScopeSelection":
        """Seed from existing chip scope so the dialog reflects current state."""
        if includes:
            overrides = {p.rstrip("/"): True for p in includes}
            overrides.update({p.rstrip("/"): False for p in excludes})
            return cls(cls.MODE_SELECTED, overrides)
        return cls(cls.MODE_ALL, {p.rstrip("/"): False for p in excludes})

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.overrides = {}

    # -- state queries ---------------------------------------------------

    def _default(self) -> bool:
        return self.mode == self.MODE_ALL

    def _nearest_override(self, path: str, include_self: bool = True):
        """(ancestor_path, state) of the deepest override covering path, or None."""
        best: Optional[Tuple[str, bool]] = None
        for p, state in self.overrides.items():
            if (include_self and p == path) or _is_under(path, p):
                if best is None or len(p) > len(best[0]):
                    best = (p, state)
        return best

    def effective(self, path: str) -> bool:
        """Would this folder be searched?"""
        found = self._nearest_override(path.rstrip("/"))
        return found[1] if found else self._default()

    def inherited(self, path: str) -> bool:
        """Effective state ignoring the folder's own override."""
        found = self._nearest_override(path.rstrip("/"), include_self=False)
        return found[1] if found else self._default()

    def display_state(self, path: str) -> str:
        """'checked' | 'unchecked' | 'partial' for checkbox rendering."""
        path = path.rstrip("/")
        eff = self.effective(path)
        for p, state in self.overrides.items():
            if _is_under(p, path) and state != eff:
                return "partial"
        return "checked" if eff else "unchecked"

    # -- mutation ----------------------------------------------------------

    def toggle(self, path: str) -> Tuple[bool, str]:
        """Toggle a folder's checkbox. Returns (ok, message-if-blocked).

        Partial state resolves to fully-checked first (standard tree behavior).
        """
        path = path.rstrip("/")
        if not path:
            return False, "Cannot toggle the root — use the mode selector instead."

        desired = self.display_state(path) != "checked"

        # A checked override cannot sit below an excluded ancestor: the search
        # API's excluded_path_prefixes always win, so it would silently do nothing.
        if desired:
            anc = self._nearest_override(path, include_self=False)
            if anc is not None and anc[1] is False:
                return False, (
                    f"Cannot re-include inside an excluded folder — "
                    f"remove the exclusion on '{anc[0]}' first."
                )

        # Subtree reset: this toggle supersedes all decisions below it.
        self.overrides = {
            p: s for p, s in self.overrides.items() if not _is_under(p, path)
        }
        if desired == self.inherited(path):
            self.overrides.pop(path, None)
        else:
            self.overrides[path] = desired
        return True, ""

    # -- output ------------------------------------------------------------

    def compile(self) -> Tuple[List[str], List[str]]:
        """Minimal (includes, excludes) prefix lists for the search API."""
        includes: List[str] = []
        excludes: List[str] = []
        for path, state in self.overrides.items():
            if state != self.inherited(path):
                (includes if state else excludes).append(path)
        return sorted(includes), sorted(excludes)

    def is_empty_selection(self) -> bool:
        """True when 'selected' mode has no included folder (matches nothing)."""
        return self.mode == self.MODE_SELECTED and not any(
            self.overrides.values()
        )


_STATE_TO_QT = {
    "checked": Qt.Checked,
    "unchecked": Qt.Unchecked,
    "partial": Qt.PartiallyChecked,
}


class ScopeTreeModel(DocumentTreeModel):
    """DocumentTreeModel with tri-state checkboxes on folders."""

    toggle_rejected = Signal(str)

    def __init__(self, api_client, selection: ScopeSelection,
                 parent=None, source="postgres"):
        super().__init__(api_client, parent, source=source)
        self.selection = selection

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid() and index.column() == COL_NAME:
            node = self.node_for_index(index)
            if node.node_type == "folder":
                return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if role == Qt.CheckStateRole and index.isValid() and index.column() == COL_NAME:
            node = self.node_for_index(index)
            if node.node_type == "folder":
                return _STATE_TO_QT[self.selection.display_state(node.path)]
            return None
        return super().data(index, role)

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        node = self.node_for_index(index)
        if node.node_type != "folder":
            return False
        ok, message = self.selection.toggle(node.path)
        if not ok:
            self.toggle_rejected.emit(message)
            return False
        self.refresh_check_states()
        return True

    def refresh_check_states(self) -> None:
        """Re-emit check state for every loaded row (ancestors turn partial)."""
        self._emit_check_changed(QModelIndex())

    def _emit_check_changed(self, parent: QModelIndex) -> None:
        rows = self.rowCount(parent)
        if rows:
            top = self.index(0, COL_NAME, parent)
            bottom = self.index(rows - 1, COL_NAME, parent)
            self.dataChanged.emit(top, bottom, [Qt.CheckStateRole])
            for row in range(rows):
                self._emit_check_changed(self.index(row, COL_NAME, parent))


class SearchScopeDialog(QDialog):
    """Pick folders to include/exclude for search via a checkbox tree."""

    def __init__(self, api_client, source: str = "postgres",
                 includes: Optional[List[str]] = None,
                 excludes: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Scope")
        self.resize(560, 480)

        self.selection = ScopeSelection.from_scope(includes or [], excludes or [])

        layout = QVBoxLayout(self)

        self._all_radio = QRadioButton("Search everything — uncheck folders to exclude")
        self._selected_radio = QRadioButton("Search only checked folders")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._all_radio)
        mode_group.addButton(self._selected_radio)
        (self._selected_radio if self.selection.mode == ScopeSelection.MODE_SELECTED
         else self._all_radio).setChecked(True)
        self._all_radio.toggled.connect(self._on_mode_changed)
        layout.addWidget(self._all_radio)
        layout.addWidget(self._selected_radio)

        self.tree = QTreeView(self)
        self.model = ScopeTreeModel(api_client, self.selection, self, source=source)
        self.model.toggle_rejected.connect(self._show_hint)
        self.tree.setModel(self.model)
        self.tree.setColumnWidth(COL_NAME, 300)
        layout.addWidget(self.tree)
        self.model.load_root()

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #f59e0b;")
        layout.addWidget(self.hint_label)

        buttons_row = QHBoxLayout()
        clear_btn = QPushButton("Reset")
        clear_btn.setToolTip("Remove every include/exclude decision")
        clear_btn.clicked.connect(self._reset)
        buttons_row.addWidget(clear_btn)
        buttons_row.addStretch()
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        self.button_box.accepted.connect(self._accept_if_valid)
        self.button_box.rejected.connect(self.reject)
        buttons_row.addWidget(self.button_box)
        layout.addLayout(buttons_row)

    def _on_mode_changed(self, _checked: bool) -> None:
        mode = (ScopeSelection.MODE_ALL if self._all_radio.isChecked()
                else ScopeSelection.MODE_SELECTED)
        self.selection.set_mode(mode)
        self.hint_label.setText(
            "Check the folders to search." if mode == ScopeSelection.MODE_SELECTED
            else ""
        )
        self.model.refresh_check_states()

    def _reset(self) -> None:
        self.selection.overrides = {}
        self.hint_label.setText("")
        self.model.refresh_check_states()

    def _show_hint(self, message: str) -> None:
        self.hint_label.setText(message)

    def _accept_if_valid(self) -> None:
        if self.selection.is_empty_selection():
            self._show_hint(
                "No folders are checked — this scope would match nothing. "
                "Check at least one folder or switch to 'Search everything'."
            )
            return
        self.accept()

    def done(self, result: int) -> None:
        # The model dies with this dialog; don't leave fetch threads running.
        self.model.shutdown_workers()
        super().done(result)

    def selected_scope(self) -> Tuple[List[str], List[str]]:
        """(includes, excludes) after the dialog is accepted."""
        return self.selection.compile()
