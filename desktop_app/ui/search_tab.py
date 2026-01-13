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
from PySide6.QtGui import QColor
from .shared import populate_document_type_combo
from .workers import SearchWorker
from ..utils.snippet_utils import extract_snippet

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
        self.setup_ui()
    
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
        
        search_layout.addLayout(query_layout)
        layout.addWidget(search_group)
        
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
        options_layout.addWidget(self.min_score_spin)
        
        # Metric
        options_layout.addWidget(QLabel("Metric:"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["cosine", "euclidean", "dot_product"])
        self.metric_combo.setMinimumWidth(120)
        self.metric_combo.setMinimumHeight(35)  # Prevent crushing at min window height
        options_layout.addWidget(self.metric_combo)
        
        options_layout.addStretch()
        layout.addWidget(options_group)

        # Document type filter
        type_group = QGroupBox("Document Type Filter (Optional)")
        type_layout = QHBoxLayout(type_group)
        type_layout.addWidget(QLabel("Document Type:"))
        self.type_filter = QComboBox()
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
        
        if not self.api_client.is_api_available():
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not available. Please make sure Docker containers are running."
            )
            return
        
        # Disable UI during search
        self.search_btn.setEnabled(False)
        self.query_input.setEnabled(False)
        self.status_label.setText(f"Searching for: {query}...")
        self.status_label.setStyleSheet("color: #2563eb; font-style: italic;")
        
        # Start search worker
        selected_type = self.type_filter.currentText().strip() if hasattr(self, "type_filter") else ""
        
        # Handle wildcard and empty type
        if selected_type == "*":
            document_type = None  # No filter (all types)
        else:
            document_type = selected_type  # Specific type or empty string (for "No Type")

        self.search_worker = SearchWorker(
            self.api_client,
            query,
            self.top_k_spin.value(),
            self.min_score_spin.value(),
            self.metric_combo.currentText(),
            document_type=document_type
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
            self.status_label.setText(f"Found {len(results)} results")
            self.status_label.setStyleSheet("color: #10b981; font-style: italic;")
        else:
            error_msg = data
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
