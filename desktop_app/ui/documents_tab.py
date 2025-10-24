"""
Documents tab for viewing and managing indexed documents.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QGroupBox, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal, QPoint
from PySide6.QtGui import QColor

import requests
from pathlib import Path
import os
import sys
import subprocess

logger = logging.getLogger(__name__)


class DocumentsWorker(QThread):
    """Worker thread for loading documents."""
    
    finished = Signal(bool, object)  # success, documents or error message
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
    
    def run(self):
        """Load documents list."""
        try:
            documents = self.api_client.list_documents()
            self.finished.emit(True, documents)
        except requests.RequestException as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class DeleteWorker(QThread):
    """Worker thread for deleting a document."""
    
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, api_client, document_id: str):
        super().__init__()
        self.api_client = api_client
        self.document_id = document_id
    
    def run(self):
        """Delete the document."""
        try:
            self.api_client.delete_document(self.document_id)
            self.finished.emit(True, "Document deleted successfully")
        except requests.RequestException as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class DocumentsTab(QWidget):
    """Tab for managing documents."""
    
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.source_manager: Optional[object] = None
        self.documents_worker = None
        self.delete_worker = None
        self.current_documents = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title and refresh button
        header_layout = QHBoxLayout()
        title = QLabel("📚 Document Library")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.load_documents)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Documents table
        table_group = QGroupBox("Indexed Documents")
        table_layout = QVBoxLayout(table_group)
        
        self.documents_table = QTableWidget()
        self.documents_table.setColumnCount(6)
        self.documents_table.setHorizontalHeaderLabels([
            "Source URI", "Document Type", "Chunks", "Created", "Updated", "Actions"
        ])
        self.documents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.documents_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.documents_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.documents_table.cellClicked.connect(self.handle_documents_cell_clicked)
        self.documents_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.documents_table.customContextMenuRequested.connect(self.show_documents_context_menu)
        self.documents_table.viewport().setCursor(Qt.PointingHandCursor)
        table_layout.addWidget(self.documents_table)
        
        layout.addWidget(table_group)
        
        # Status label
        self.status_label = QLabel("Click Refresh to load documents")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)
        
        # Auto-load on first show
        self.load_documents()
    
    def load_documents(self):
        """Load the list of documents."""
        if not self.api_client.is_api_available():
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not available. Please make sure Docker containers are running."
            )
            return
        
        # Disable UI during load
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("Loading documents...")
        self.status_label.setStyleSheet("color: #2563eb; font-style: italic;")
        
        # Start worker
        self.documents_worker = DocumentsWorker(self.api_client)
        self.documents_worker.finished.connect(self.documents_loaded)
        self.documents_worker.start()
    
    def documents_loaded(self, success: bool, data):
        """Handle documents load completion."""
        # Re-enable UI
        self.refresh_btn.setEnabled(True)
        
        if success:
            self.current_documents = data
            self.display_documents(data)
            self.status_label.setText(f"Loaded {len(data)} documents")
            self.status_label.setStyleSheet("color: #059669; font-style: italic;")
        else:
            error_msg = data
            QMessageBox.critical(self, "Load Failed", f"Failed to load documents: {error_msg}")
            self.status_label.setText("Load failed")
            self.status_label.setStyleSheet("color: #dc2626; font-style: italic;")
    
    def display_documents(self, documents: List[Dict[str, Any]]):
        """Display documents in the table."""
        self.documents_table.setRowCount(len(documents))
        
        for i, doc in enumerate(documents):
            # Source URI
            source_item = self._create_source_item(doc.get('source_uri', ''))
            self.documents_table.setItem(i, 0, source_item)
            
            # Document Type: prefer metadata.type, fallback to document_type
            metadata = doc.get('metadata', {})
            doc_type = 'Unknown'
            if isinstance(metadata, dict) and metadata.get('type'):
                doc_type = metadata.get('type')
            elif doc.get('document_type'):
                doc_type = doc.get('document_type')
            type_item = QTableWidgetItem(doc_type)
            type_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 1, type_item)
            
            # Chunk count
            chunks_item = QTableWidgetItem(str(doc.get('chunk_count', 0)))
            chunks_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 2, chunks_item)
            
            # Created date (API returns 'indexed_at')
            created = doc.get('indexed_at', '')
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    created = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            created_item = QTableWidgetItem(created)
            created_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 3, created_item)
            
            # Updated date (API returns 'last_updated')
            updated = doc.get('last_updated', '')
            if updated:
                try:
                    dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                    updated = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            updated_item = QTableWidgetItem(updated)
            updated_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 4, updated_item)
            
            # Actions - Delete button
            delete_btn = QPushButton("🗑️ Delete")
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc2626;
                    color: white;
                    border-radius: 3px;
                    padding: 5px 10px;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                }
            """)
            delete_btn.clicked.connect(lambda checked, doc_id=doc.get('document_id'): self.delete_document(doc_id))
            self.documents_table.setCellWidget(i, 5, delete_btn)
        
        self.documents_table.resizeRowsToContents()

    def delete_document(self, document_id: str):
        """Delete a document."""
        # Find document name for confirmation
        doc_name = "this document"
        for doc in self.current_documents:
            if doc.get('document_id') == document_id:
                doc_name = doc.get('source_uri', 'this document')
                break
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete:\n\n{doc_name}\n\nThis will remove all chunks and cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.status_label.setText(f"Deleting document...")
            self.status_label.setStyleSheet("color: #2563eb; font-style: italic;")
            
            # Start delete worker
            self.delete_worker = DeleteWorker(self.api_client, document_id)
            self.delete_worker.finished.connect(self.delete_finished)
            self.delete_worker.start()
    
    def delete_finished(self, success: bool, message: str):
        """Handle delete completion."""
        if success:
            QMessageBox.information(self, "Success", message)
            # Reload documents
            self.load_documents()
        else:
            QMessageBox.critical(self, "Delete Failed", f"Failed to delete document: {message}")
            self.status_label.setText("Delete failed")
            self.status_label.setStyleSheet("color: #dc2626; font-style: italic;")

    def _create_source_item(self, source_uri: str) -> QTableWidgetItem:
        """Create a hyperlink-style item for source URIs."""
        display_text = source_uri or "Unknown"
        item = QTableWidgetItem(display_text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, source_uri)
        item.setToolTip(source_uri)

        if source_uri:
            font = item.font()
            font.setUnderline(True)
            item.setFont(font)
            item.setForeground(QColor("#1a73e8"))
            item.setToolTip("Open this file with the default application")

        return item

    def handle_documents_cell_clicked(self, row: int, column: int) -> None:
        """Open source path when source column is clicked."""
        if column != 0:
            return

        item = self.documents_table.item(row, column)
        if item is None:
            return

        source_uri = item.data(Qt.UserRole) or item.text()
        if self.source_manager:
            self.source_manager.open_path(source_uri)
        else:
            self.open_source_path(source_uri)

    def show_documents_context_menu(self, pos: QPoint) -> None:
        if not self.source_manager:
            return

        index = self.documents_table.indexAt(pos)
        if not index.isValid() or index.column() != 0:
            return

        item = self.documents_table.item(index.row(), index.column())
        if item is None:
            return

        source_uri = item.data(Qt.UserRole) or item.text()
        menu = QMenu(self)

        open_action = menu.addAction("Open")
        open_with_action = menu.addAction("Open with…")
        show_in_folder_action = menu.addAction("Show in Folder")
        copy_path_action = menu.addAction("Copy Path")
        reindex_action = menu.addAction("Reindex Now")

        action = menu.exec(self.documents_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == open_action:
            self.source_manager.open_path(source_uri)
        elif action == open_with_action:
            self.source_manager.open_path(source_uri, mode="open_with")
        elif action == show_in_folder_action:
            self.source_manager.open_path(source_uri, mode="show_in_folder", prompt_reindex=False)
        elif action == copy_path_action:
            self.source_manager.open_path(source_uri, mode="copy_path", prompt_reindex=False)
        elif action == reindex_action:
            self.source_manager.trigger_reindex_path(source_uri)

    def open_source_path(self, path: str) -> None:
        """Open the given path with the OS default application."""
        if not path or path == "Unknown":
            QMessageBox.warning(
                self,
                "No Path",
                "No source path is available to open."
            )
            return

        normalized = Path(path)
        if not normalized.exists():
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The file does not exist:\n{path}"
            )
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(normalized))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(normalized)])
            else:
                subprocess.Popen(["xdg-open", str(normalized)])
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open Failed",
                f"Unable to open the file:\n{path}\n\nError: {exc}"
            )
