"""
Search tab for querying indexed documents.
"""

import logging
import sys
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QMessageBox, QMenu, QHeaderView
)
import qtawesome as qta
from PySide6.QtCore import Qt, QThread, Signal, QPoint, QSize
from PySide6.QtGui import QColor, QStandardItemModel, QStandardItem


class CheckableComboBox(QComboBox):
    """A combobox where each item has a checkbox, supporting multi-selection."""

    def __init__(self, placeholder: str = "All", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._suppress_hide = False

        self._model = QStandardItemModel(self)
        self.setModel(self._model)

        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(placeholder)
        # Disable the autocompleter — it interferes with the custom model
        self.setCompleter(None)
        self.setCurrentIndex(-1)

        self.view().pressed.connect(self._toggle_item)
        # When QComboBox auto-selects index 0 after the first item is added it
        # overwrites the line edit text.  Reset to our custom display each time.
        self.currentIndexChanged.connect(lambda _: self._refresh_text())
        self._refresh_text()

    # Text of the "select all" sentinel item.
    SELECT_ALL = "*"

    def _toggle_item(self, index):
        item = self._model.itemFromIndex(index)
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)

        if new_state == Qt.Checked:
            if item.text() == self.SELECT_ALL:
                # "*" checked → uncheck every specific extension
                for i in range(self._model.rowCount()):
                    other = self._model.item(i)
                    if other.text() != self.SELECT_ALL:
                        other.setData(Qt.Unchecked, Qt.CheckStateRole)
            else:
                # Specific extension checked → uncheck "*"
                for i in range(self._model.rowCount()):
                    other = self._model.item(i)
                    if other.text() == self.SELECT_ALL:
                        other.setData(Qt.Unchecked, Qt.CheckStateRole)
                        break

        # If nothing is checked (user unchecked * or last specific ext),
        # fall back to "*" so the field is never blank.
        if not self._raw_checked():
            for i in range(self._model.rowCount()):
                other = self._model.item(i)
                if other.text() == self.SELECT_ALL:
                    other.setData(Qt.Checked, Qt.CheckStateRole)
                    break

        self._suppress_hide = True  # keep popup open after toggling
        self._refresh_text()

    def hidePopup(self):
        # Suppress one close triggered by the item click so users can
        # check multiple extensions without reopening the dropdown each time.
        # Use getattr guard: Qt can call this override before __init__ sets the attr.
        if getattr(self, "_suppress_hide", False):
            self._suppress_hide = False
            return
        super().hidePopup()

    def _refresh_text(self):
        self.setCurrentIndex(-1)
        raw = self._raw_checked()
        self.lineEdit().setText(", ".join(raw) if raw else "")

    def add_item(self, text: str, checked: bool = False):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemIsEnabled)  # No ItemIsUserCheckable — we toggle manually
        item.setData(Qt.Checked if checked else Qt.Unchecked, Qt.CheckStateRole)
        self._model.appendRow(item)
        self._refresh_text()

    def clear_items(self):
        self._model.clear()
        self._refresh_text()

    def _raw_checked(self) -> list:
        """All checked item texts, including the '*' sentinel."""
        return [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i).checkState() == Qt.Checked
        ]

    def checked_items(self) -> list:
        """Checked items suitable for use as a search filter.
        Returns [] when '*' is the only selection (meaning 'all — no filter')."""
        raw = self._raw_checked()
        if not raw or raw == [self.SELECT_ALL]:
            return []
        return [t for t in raw if t != self.SELECT_ALL]
from .shared import populate_document_type_combo
from .styles.theme import Theme
from .workers import SearchWorker
from ..utils.snippet_utils import extract_snippet
from ..utils import app_config
from ..utils.search_limits import candidate_limit_for_unique_files

# ... imports ...

logger = logging.getLogger(__name__)

class SearchTab(QWidget):
    """Tab for searching documents."""
    
    def __init__(self, api_client, parent=None, source_manager: Optional[object] = None):
        super().__init__(parent)
        self.api_client = api_client
        self.search_worker = None
        self.source_manager = source_manager
        self.current_query = ""  # Store for snippet extraction
        self._display_result_limit = 10
        self._active_engine = "lancedb"
        self._scope_includes: List[str] = []
        self._scope_excludes: List[str] = []
        self.setup_ui()

    def clear_results(self) -> None:
        """Drop any displayed search results — called when the connected
        account/key changes so one user's results don't linger for the next."""
        try:
            self.results_table.setRowCount(0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Folder scope (include/exclude prefixes fed from the Documents tree)
    # ------------------------------------------------------------------

    def add_scope_include(self, folder_path: str) -> None:
        """Restrict the next searches to this folder (additive with other includes)."""
        from ..utils.path_scope import is_path_under

        path = folder_path.rstrip("/")
        if not path:
            return
        # Server-side excludes always win, so an include under an excluded
        # ancestor would silently match nothing — drop the conflicting
        # excludes (the user's newest intent is to search this folder).
        self._scope_excludes = [
            e for e in self._scope_excludes
            if e != path and not is_path_under(path, e)
        ]
        if path not in self._scope_includes:
            self._scope_includes.append(path)
        self._refresh_scope_chips()

    def add_scope_exclude(self, folder_path: str) -> None:
        """Exclude this folder from the next searches."""
        from ..utils.path_scope import is_path_under

        path = folder_path.rstrip("/")
        if not path:
            return
        # Includes at or below the new exclude would be dead (excludes win
        # server-side) — remove them so the chips never show a scope that
        # silently matches nothing.
        self._scope_includes = [
            i for i in self._scope_includes
            if i != path and not is_path_under(i, path)
        ]
        if path not in self._scope_excludes:
            self._scope_excludes.append(path)
        self._refresh_scope_chips()

    def clear_scope(self) -> None:
        """Remove all folder include/exclude restrictions."""
        self._scope_includes = []
        self._scope_excludes = []
        self._refresh_scope_chips()

    def open_scope_dialog(self) -> None:
        """Open the folder checkbox tree and apply the resulting scope."""
        from PySide6.QtWidgets import QDialog
        from .search_scope_dialog import SearchScopeDialog

        engine = self.engine_combo.currentData() if hasattr(self, "engine_combo") else None
        if engine == "postgres":
            source = "postgres"
        else:
            # Match what search actually queries: perform_search sends
            # source=None and the backend falls back to Postgres when LanceDB
            # is disabled, so the picker must not show an empty LanceDB tree
            # in that state.
            try:
                self.api_client.get_document_tree_stats(source="lancedb")
                source = "lancedb"
            except Exception:
                source = "postgres"
        dialog = SearchScopeDialog(
            self.api_client,
            source=source,
            includes=self._scope_includes,
            excludes=self._scope_excludes,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            includes, excludes = dialog.selected_scope()
            self._scope_includes = list(includes)
            self._scope_excludes = list(excludes)
            self._refresh_scope_chips()

    def scope_filters(self) -> Optional[Dict[str, Any]]:
        """Active scope as search-API filter keys, or None when unscoped."""
        filters: Dict[str, Any] = {}
        if self._scope_includes:
            filters["path_prefixes"] = list(self._scope_includes)
        if self._scope_excludes:
            filters["excluded_path_prefixes"] = list(self._scope_excludes)
        return filters or None

    def _remove_scope_entry(self, path: str, exclude: bool) -> None:
        target = self._scope_excludes if exclude else self._scope_includes
        if path in target:
            target.remove(path)
        self._refresh_scope_chips()

    def _refresh_scope_chips(self) -> None:
        """Rebuild the chip row to mirror the current scope lists."""
        while self._scope_chip_layout.count():
            item = self._scope_chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for path, exclude in (
            [(p, False) for p in self._scope_includes]
            + [(p, True) for p in self._scope_excludes]
        ):
            name = path.rstrip("/").rsplit("/", 1)[-1] or path
            chip = QPushButton(f"✕ {'not ' if exclude else ''}{name}")
            role = "Excluding" if exclude else "Only searching"
            chip.setToolTip(f"{role}: {path}\nClick to remove this restriction")
            chip.setStyleSheet(
                "QPushButton { border-radius: 10px; padding: 3px 10px; "
                + ("background-color: #7f1d1d; color: #fecaca; }"
                   if exclude else
                   "background-color: #1e3a5f; color: #bfdbfe; }")
            )
            chip.clicked.connect(
                lambda checked=False, p=path, e=exclude: self._remove_scope_entry(p, e)
            )
            self._scope_chip_layout.addWidget(chip)

        self.scope_group.setVisible(
            bool(self._scope_includes or self._scope_excludes)
        )


    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Search Documents")
        title.setProperty("class", "header")
        layout.addWidget(title)
        
        # Search input
        search_group = QGroupBox("Search Query")
        search_layout = QVBoxLayout(search_group)
        
        query_layout = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Enter your search query...")
        self.query_input.setMinimumHeight(40)
        self.query_input.returnPressed.connect(self.perform_search)
        query_layout.addWidget(self.query_input)
        
        self.search_btn = QPushButton("Search")
        self.search_btn.setIcon(qta.icon('fa5s.search', color='white'))
        self.search_btn.clicked.connect(self.perform_search)
        self.search_btn.setMinimumHeight(40)
        self.search_btn.setProperty("class", "primary")
        query_layout.addWidget(self.search_btn)

        self.scope_btn = QPushButton("Scope…")
        self.scope_btn.setIcon(qta.icon('fa5s.folder-open', color='#9ca3af'))
        self.scope_btn.setToolTip(
            "Limit the search to specific folders, or exclude folders"
        )
        self.scope_btn.clicked.connect(self.open_scope_dialog)
        self.scope_btn.setMinimumHeight(40)
        query_layout.addWidget(self.scope_btn)
        
        search_layout.addLayout(query_layout)
        layout.addWidget(search_group)

        # Folder scope chips — populated via the Documents tree context menu.
        # Hidden while no scope is active so the default layout is unchanged.
        self.scope_group = QGroupBox("Search Scope (Folders)")
        scope_outer = QHBoxLayout(self.scope_group)
        self._scope_chip_layout = QHBoxLayout()
        self._scope_chip_layout.setSpacing(6)
        scope_outer.addLayout(self._scope_chip_layout)
        scope_outer.addStretch()
        self.clear_scope_btn = QPushButton("Clear Scope")
        self.clear_scope_btn.setToolTip("Remove all folder include/exclude restrictions")
        self.clear_scope_btn.clicked.connect(self.clear_scope)
        scope_outer.addWidget(self.clear_scope_btn)
        self.scope_group.setVisible(False)
        layout.addWidget(self.scope_group)

        # Search options
        options_group = QGroupBox("Search Options")
        options_layout = QHBoxLayout(options_group)
        
        # Top K
        options_layout.addWidget(QLabel("Results:"))
        self.top_k_spin = QSpinBox()
        self.top_k_spin.setRange(1, 100)
        self.top_k_spin.setValue(10)
        self.top_k_spin.setMinimumWidth(80)
        options_layout.addWidget(self.top_k_spin)
        
        # Min Score
        options_layout.addWidget(QLabel("Min Score:"))
        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(0.0, 1.0)
        self.min_score_spin.setSingleStep(0.05)
        self.min_score_spin.setValue(0.3)
        self.min_score_spin.setMinimumWidth(80)
        options_layout.addWidget(self.min_score_spin)        # Metric
        from PySide6.QtWidgets import QListView
        options_layout.addWidget(QLabel("Metric:"))
        self.metric_combo = QComboBox()
        self.metric_combo.setView(QListView())
        self.metric_combo.addItems(["cosine", "euclidean", "dot_product"])
        self.metric_combo.setMinimumWidth(120)
        self.metric_combo.setMinimumHeight(35)  # Prevent crushing at min window height
        options_layout.addWidget(self.metric_combo)
        
        # Engine
        options_layout.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        self.engine_combo.setView(QListView())
        self.engine_combo.addItem("LanceDB", "lancedb")          # index 0 = default
        self.engine_combo.addItem("Postgres (debug)", "postgres")
        self.engine_combo.setMinimumHeight(35)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        options_layout.addWidget(self.engine_combo)
        
        options_layout.addStretch()
        layout.addWidget(options_group)
 
        # Document type filter
        type_group = QGroupBox("Document Type Filter (Optional)")
        type_layout = QHBoxLayout(type_group)
        type_layout.addWidget(QLabel("Document Type:"))
        self.type_filter = QComboBox()
        self.type_filter.setView(QListView())
        self.type_filter.setEditable(True)
        # We will populate this dynamically, but default is *
        self.type_filter.addItem("*")
        self.type_filter.setPlaceholderText("(optional)")
        self.type_filter.setToolTip("Filter by document type. Use * for all, or leave empty for no type.")
        self.type_filter.setMinimumWidth(200)
        self.type_filter.setMinimumHeight(35)  # Prevent crushing at min window height
        type_layout.addWidget(self.type_filter)

        refresh_types_btn = QPushButton()
        refresh_types_btn.setIcon(qta.icon('fa5s.sync-alt', color='#9ca3af'))
        refresh_types_btn.clicked.connect(self.load_document_types)
        refresh_types_btn.setToolTip("Refresh available document types")
        refresh_types_btn.setFixedSize(30, 30)
        type_layout.addWidget(refresh_types_btn)
        
        type_layout.addStretch()
        layout.addWidget(type_group)

        # File extension filter
        ext_group = QGroupBox("File Extension Filter (Optional)")
        ext_layout = QHBoxLayout(ext_group)
        ext_layout.addWidget(QLabel("Extensions:"))
        self.ext_filter = CheckableComboBox(placeholder="All extensions")
        self.ext_filter.setMinimumWidth(200)
        self.ext_filter.setMinimumHeight(35)
        self.ext_filter.setToolTip(
            "Filter results by file extension. Check one or more extensions, or leave blank for all."
        )
        ext_layout.addWidget(self.ext_filter)

        refresh_ext_btn = QPushButton()
        refresh_ext_btn.setIcon(qta.icon('fa5s.sync-alt', color='#9ca3af'))
        refresh_ext_btn.clicked.connect(self.load_extensions)
        refresh_ext_btn.setToolTip("Refresh available file extensions")
        refresh_ext_btn.setFixedSize(30, 30)
        ext_layout.addWidget(refresh_ext_btn)

        ext_layout.addStretch()
        layout.addWidget(ext_group)

        # Load document types on init - DEFERRED to MainWindow
        # self.load_document_types()

        # Results table
        results_group = QGroupBox("Search Results")
        results_layout = QVBoxLayout(results_group)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["Score", "Type", "Source", "Chunk", "Content Preview"])
        self.results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.cellClicked.connect(self.handle_results_cell_clicked)
        self.results_table.doubleClicked.connect(self.show_full_content)
        self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.show_results_context_menu)
        self.results_table.viewport().setCursor(Qt.PointingHandCursor)
        results_layout.addWidget(self.results_table)
        
        layout.addWidget(results_group)
        
        # Status label
        self.status_label = QLabel("Enter a query and click Search")
        self.status_label.setProperty("class", "subtitle")
        layout.addWidget(self.status_label)
    
    def perform_search(self):
        """Execute the search."""
        query = self.query_input.text().strip()
        
        if not query:
            QMessageBox.warning(self, "Empty Query", "Please enter a search query.")
            return
        
        # Store query for snippet extraction
        self.current_query = query
        
        selected_type = self.type_filter.currentText().strip() if hasattr(self, "type_filter") else ""

        # Handle wildcard and empty type
        if selected_type == "*":
            document_type = None  # No filter (all types)
        else:
            document_type = selected_type  # Specific type or empty string (for "No Type")

        extensions = self.ext_filter.checked_items() if hasattr(self, "ext_filter") else []

        self._display_result_limit = self.top_k_spin.value()


        health = self.api_client.get_health()
        if health.get("status") == "initializing":
            QMessageBox.information(
                self,
                "Backend Initializing",
                "The backend is currently loading AI models.\n\n"
                "Please wait for the status bar to show 'Ready' before searching."
            )
            return
            
        if health.get("status") == "unreachable":
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not reachable. Please make sure Docker containers are running."
            )
            return

        # Disable UI during search
        self.search_btn.setEnabled(False)
        self.query_input.setEnabled(False)
        self.status_label.setText(f"Searching for: {query}...")
        self.status_label.setStyleSheet("color: #2563eb; font-style: italic;")

        # Start search worker
        candidate_limit = self._display_result_limit

        engine = self.engine_combo.currentData()          # "lancedb" | "postgres"
        self._active_engine = engine
        source = "postgres" if engine == "postgres" else None

        self.search_worker = SearchWorker(
            self.api_client,
            query,
            candidate_limit,
            self.min_score_spin.value(),
            self.metric_combo.currentText(),
            document_type=document_type,
            extensions=extensions or None,
            group_by_document=True,
            literal_tail_suppression="identifier-token",
            source=source,
            filters=self.scope_filters(),
        )
        self.search_worker.finished.connect(self.search_finished)
        self.search_worker.start()


    
    def search_finished(self, success: bool, data):
        """Handle search completion."""
        # Re-enable UI
        self.search_btn.setEnabled(True)
        self.query_input.setEnabled(True)
        
        if success:
            results = data
            self.display_results(results)
            n = self.results_table.rowCount()
            
            # Check for empty-state message from backend
            backend_msg = getattr(self.api_client, "last_search_message", None)
            if backend_msg and isinstance(backend_msg, str):
                self.status_label.setText(backend_msg)
                self.status_label.setStyleSheet("color: #f59e0b; font-style: italic; font-weight: bold;")

            else:
                suffix = " (1 per file)"
                if self._active_engine == "postgres":
                    self.status_label.setText(f"Found {n} result{'s' if n != 1 else ''}{suffix} · ⚠ Postgres (debug) engine — not the product engine")
                    self.status_label.setStyleSheet("color: #f59e0b; font-style: italic; font-weight: bold;")
                else:
                    self.status_label.setText(f"Found {n} result{'s' if n != 1 else ''}{suffix}")
                    self.status_label.setStyleSheet("color: #10b981; font-style: italic;")
        else:
            error_msg = str(data)
            is_503 = False
            if hasattr(data, 'status_code') and data.status_code == 503:
                is_503 = True

            if is_503:
                self.results_table.setRowCount(0)
                friendly_msg = f"{error_msg} — Open the Documents tab (tree) and refresh to check sync status."
                self.status_label.setText(friendly_msg)
                self.status_label.setStyleSheet("color: #f59e0b; font-style: italic; font-weight: bold;")
            else:
                QMessageBox.critical(self, "Search Failed", f"Search failed: {error_msg}")
                self.status_label.setText("Search failed")
                self.status_label.setStyleSheet("color: #ef4444; font-style: italic;")

    
    def display_results(self, results: List[Dict[str, Any]]):
        """Display search results in the table."""
        # Comprehensive defensive handling
        if results is None:
            logger.warning("Search returned None results")
            results = []
        elif not isinstance(results, list):
            logger.warning(f"Search returned non-list: {type(results)}")
            results = []
        
        # Filter out None items
        valid_results = []
        for r in results:
            if r is not None and isinstance(r, dict):
                valid_results.append(r)
            else:
                logger.warning(f"Skipping invalid result: {r}")

        # Deduplicate: keep only the best-scored chunk per source file.
        # Results arrive sorted by score descending so the first occurrence wins.
        seen_uris: set = set()
        deduped = []
        for r in valid_results:
            uri = r.get('source_uri', '')
            if uri not in seen_uris:
                seen_uris.add(uri)
                deduped.append(r)
        valid_results = deduped[:self._display_result_limit]

        self.results_table.setRowCount(len(valid_results))
        
        for i, result in enumerate(valid_results):
            augmented = self._augment_result(result)

            # Score
            score_item = QTableWidgetItem(f"{augmented['display_score']:.4f}")
            score_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(i, 0, score_item)
            
            # Document Type (Col 1) - with null safety
            doc_type = "-"
            if result:
                doc_type = result.get('document_type') or (result.get('metadata') or {}).get('type') or "-"
            type_item = QTableWidgetItem(str(doc_type))
            type_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(i, 1, type_item)

            # Source URI (Col 2)
            source_item = self._create_source_item(result.get('source_uri', 'Unknown'))
            self.results_table.setItem(i, 2, source_item)
            
            # Chunk number (Col 3)
            chunk_item = QTableWidgetItem(str(augmented['display_chunk']))
            chunk_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(i, 3, chunk_item)
            
            # Content preview (Col 4) - extract relevant snippet around query terms
            content = result.get('text_content', '')
            preview = extract_snippet(content, self.current_query, window=120)
            content_item = QTableWidgetItem(preview)
            self.results_table.setItem(i, 4, content_item)
            
            # Store full result in row
            self.results_table.item(i, 0).setData(Qt.UserRole, augmented)
        
        self.results_table.resizeRowsToContents()

    def show_full_content(self, index):
        """Show full content of selected result."""
        row = index.row()
        result = self.results_table.item(row, 0).data(Qt.UserRole)

        if result:
            content = result.get('text_content', 'No content')
            source = result.get('source_uri', 'Unknown')
            score = result.get('display_score', 0.0)
            chunk = result.get('display_chunk', 0)
            doc_type = result.get('document_type') or result.get('metadata', {}).get('type') or "Unknown"

            msg = QMessageBox(self)
            msg.setWindowTitle("Full Content")
            msg.setText(f"Source: {source}\nType: {doc_type}\nChunk: {chunk}\nScore: {score:.4f}")
            msg.setDetailedText(content)
            msg.exec()

    def _create_source_item(self, source_uri: str) -> QTableWidgetItem:
        """Create table item for clickable source URI."""
        item = QTableWidgetItem(source_uri or "Unknown")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, source_uri)

        if source_uri:
            font = item.font()
            font.setUnderline(True)
            item.setFont(font)
            item.setForeground(QColor("#6366f1"))
            item.setToolTip("Open this file with the default application")

        return item

    def handle_results_cell_clicked(self, row: int, column: int) -> None:
        """Handle clicks on the results table."""
        # Source is now in column 2 (0=Score, 1=Type, 2=Source)
        if column != 2:
            return

        item = self.results_table.item(row, column)
        if item is None:
            return

        source_uri = item.data(Qt.UserRole) or item.text()
        if self.source_manager:
            self.source_manager.open_path(source_uri)
        else:
            QMessageBox.warning(
                self,
                "Feature Unavailable",
                "File opening is not available. Please restart the application."
            )

    def show_results_context_menu(self, pos: QPoint) -> None:
        if not self.source_manager:
            return

        index = self.results_table.indexAt(pos)
        # Source is in column 2
        if not index.isValid() or index.column() != 2:
            return

        item = self.results_table.item(index.row(), index.column())
        if item is None:
            return

        source_uri = item.data(Qt.UserRole) or item.text()

        menu = QMenu(self)
        open_action = menu.addAction("Open")
        open_with_action = menu.addAction("Open with…")
        show_in_folder_action = menu.addAction("Show in Folder")
        copy_path_action = menu.addAction("Copy Path")

        entry = self.source_manager.find_entry(source_uri)
        queued = entry.queued if entry else False
        queue_label = "Unqueue from Reindex" if queued else "Queue for Reindex"
        queue_action = menu.addAction(queue_label)

        reindex_action = menu.addAction("Reindex Now")
        remove_action = menu.addAction("Remove from Recent")

        action = menu.exec(self.results_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == open_action:
            self.source_manager.open_path(source_uri)
        elif action == open_with_action:
            self.source_manager.open_path(source_uri, mode="open_with")
        elif action == show_in_folder_action:
            self.source_manager.open_path(source_uri, mode="show_in_folder", auto_queue=False)
        elif action == copy_path_action:
            self.source_manager.open_path(source_uri, mode="copy_path", auto_queue=False)
        elif action == queue_action:
            self.source_manager.queue_entry(source_uri, not queued)
        elif action == reindex_action:
            self.source_manager.trigger_reindex_path(source_uri)
        elif action == remove_action:
            self.source_manager.remove_entry(source_uri)
    
    def load_extensions(self) -> None:
        """Populate the extension filter from the index."""
        if not hasattr(self, "ext_filter"):
            return
        try:
            extensions = self.api_client.get_extensions()
            self.ext_filter.clear_items()
            self.ext_filter.add_item(CheckableComboBox.SELECT_ALL, checked=True)
            for ext in extensions:
                self.ext_filter.add_item(ext)
        except Exception as e:
            logger.debug(f"Could not load extensions: {e}")

    def load_document_types(self) -> None:
        """Populate the document type filter from the API."""
        if not hasattr(self, "type_filter"):
            return

        populate_document_type_combo(
            self.type_filter,
            self.api_client,
            logger,
            blank_option="*",
            log_context="Search tab"
        )
        # Add explicit option for empty/no type
        self.type_filter.addItem("", "No Type")

    def _augment_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        augmented = dict(result)

        raw_score = augmented.get('score')
        if raw_score is None:
            raw_score = augmented.get('relevance_score', 0)
        try:
            display_score = float(raw_score)
        except (TypeError, ValueError):
            display_score = 0.0
        augmented['display_score'] = display_score

        chunk_value = augmented.get('chunk_number')
        if chunk_value is None:
            chunk_value = augmented.get('chunk_index', 0)
        augmented['display_chunk'] = chunk_value

        return augmented

    def _candidate_limit_for_unique_files(self, visible_limit: int) -> int:
        """Fetch extra chunk-level matches so file-level dedupe does not hide files."""
        return candidate_limit_for_unique_files(visible_limit)

    def _on_engine_changed(self) -> None:
        """Visual feedback when Postgres engine is selected."""
        if self.engine_combo.currentData() == "postgres":
            self.engine_combo.setStyleSheet(
                "background-color: #374151; border: 1px solid #f59e0b; "
                "border-radius: 6px; color: #f9fafb; padding: 8px;"
            )
        else:
            self.engine_combo.setStyleSheet("")
