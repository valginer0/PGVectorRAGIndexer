"""
Search tab for querying indexed documents.
"""

import logging
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

import requests

logger = logging.getLogger(__name__)


class SearchWorker(QThread):
    """Worker thread for searching documents."""
    
    finished = Signal(bool, object)  # success, results or error message
    
    def __init__(self, api_client, query: str, top_k: int, min_score: float, metric: str):
        super().__init__()
        self.api_client = api_client
        self.query = query
        self.top_k = top_k
        self.min_score = min_score
        self.metric = metric
    
    def run(self):
        """Execute the search."""
        try:
            results = self.api_client.search(
                self.query,
                top_k=self.top_k,
                min_score=self.min_score,
                metric=self.metric
            )
            self.finished.emit(True, results)
        except requests.RequestException as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class SearchTab(QWidget):
    """Tab for searching documents."""
    
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.search_worker = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("🔍 Search Documents")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        # Search input
        search_group = QGroupBox("Search Query")
        search_layout = QVBoxLayout(search_group)
        
        query_layout = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Enter your search query...")
        self.query_input.returnPressed.connect(self.perform_search)
        query_layout.addWidget(self.query_input)
        
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.clicked.connect(self.perform_search)
        self.search_btn.setMinimumHeight(35)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
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
        options_layout.addWidget(self.top_k_spin)
        
        # Min Score
        options_layout.addWidget(QLabel("Min Score:"))
        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(0.0, 1.0)
        self.min_score_spin.setSingleStep(0.1)
        self.min_score_spin.setValue(0.5)
        options_layout.addWidget(self.min_score_spin)
        
        # Metric
        options_layout.addWidget(QLabel("Metric:"))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["cosine", "euclidean", "dot_product"])
        options_layout.addWidget(self.metric_combo)
        
        options_layout.addStretch()
        layout.addWidget(options_group)
        
        # Results table
        results_group = QGroupBox("Search Results")
        results_layout = QVBoxLayout(results_group)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Score", "Source", "Chunk", "Content Preview"])
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.doubleClicked.connect(self.show_full_content)
        results_layout.addWidget(self.results_table)
        
        layout.addWidget(results_group)
        
        # Status label
        self.status_label = QLabel("Enter a query and click Search")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)
    
    def perform_search(self):
        """Execute the search."""
        query = self.query_input.text().strip()
        
        if not query:
            QMessageBox.warning(self, "Empty Query", "Please enter a search query.")
            return
        
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
        self.search_worker = SearchWorker(
            self.api_client,
            query,
            self.top_k_spin.value(),
            self.min_score_spin.value(),
            self.metric_combo.currentText()
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
            self.status_label.setStyleSheet("color: #059669; font-style: italic;")
        else:
            error_msg = data
            QMessageBox.critical(self, "Search Failed", f"Search failed: {error_msg}")
            self.status_label.setText("Search failed")
            self.status_label.setStyleSheet("color: #dc2626; font-style: italic;")
    
    def display_results(self, results: List[Dict[str, Any]]):
        """Display search results in the table."""
        self.results_table.setRowCount(len(results))
        
        for i, result in enumerate(results):
            # Score
            score_item = QTableWidgetItem(f"{result.get('score', 0):.4f}")
            score_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(i, 0, score_item)
            
            # Source URI
            source_item = QTableWidgetItem(result.get('source_uri', 'Unknown'))
            self.results_table.setItem(i, 1, source_item)
            
            # Chunk number
            chunk_item = QTableWidgetItem(str(result.get('chunk_number', 0)))
            chunk_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(i, 2, chunk_item)
            
            # Content preview (first 100 chars)
            content = result.get('text_content', '')
            preview = content[:100] + "..." if len(content) > 100 else content
            content_item = QTableWidgetItem(preview)
            self.results_table.setItem(i, 3, content_item)
            
            # Store full result in row
            self.results_table.item(i, 0).setData(Qt.UserRole, result)
        
        self.results_table.resizeRowsToContents()
    
    def show_full_content(self, index):
        """Show full content of selected result."""
        row = index.row()
        result = self.results_table.item(row, 0).data(Qt.UserRole)
        
        if result:
            content = result.get('text_content', 'No content')
            source = result.get('source_uri', 'Unknown')
            score = result.get('score', 0)
            chunk = result.get('chunk_number', 0)
            
            msg = QMessageBox(self)
            msg.setWindowTitle("Full Content")
            msg.setText(f"Source: {source}\nChunk: {chunk}\nScore: {score:.4f}")
            msg.setDetailedText(content)
            msg.exec()
