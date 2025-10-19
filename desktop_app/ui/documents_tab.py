"""
Documents tab for viewing and managing indexed documents.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QGroupBox
)
from PySide6.QtCore import Qt, QThread, Signal

import requests

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
        self.documents_table.setColumnCount(5)
        self.documents_table.setHorizontalHeaderLabels([
            "Source URI", "Chunks", "Created", "Updated", "Actions"
        ])
        self.documents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.documents_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.documents_table.setEditTriggers(QTableWidget.NoEditTriggers)
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
            source_item = QTableWidgetItem(doc.get('source_uri', 'Unknown'))
            source_item.setToolTip(doc.get('source_uri', ''))
            self.documents_table.setItem(i, 0, source_item)
            
            # Chunk count
            chunks_item = QTableWidgetItem(str(doc.get('chunk_count', 0)))
            chunks_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 1, chunks_item)
            
            # Created date
            created = doc.get('created_at', '')
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    created = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            created_item = QTableWidgetItem(created)
            created_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 2, created_item)
            
            # Updated date
            updated = doc.get('updated_at', '')
            if updated:
                try:
                    dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                    updated = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            updated_item = QTableWidgetItem(updated)
            updated_item.setTextAlignment(Qt.AlignCenter)
            self.documents_table.setItem(i, 3, updated_item)
            
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
            self.documents_table.setCellWidget(i, 4, delete_btn)
        
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
