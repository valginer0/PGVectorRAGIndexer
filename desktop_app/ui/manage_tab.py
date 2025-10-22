"""
Manage Documents tab for bulk operations (delete, export, restore).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QTextEdit, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit
)
from PySide6.QtCore import Qt
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ManageTab(QWidget):
    """Tab for managing documents (bulk delete, export, restore)."""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.last_backup = None  # Store last backup for undo
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("🗂️ Manage Documents")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px 0;")
        layout.addWidget(title)
        
        # Instructions
        info_box = QGroupBox("ℹ️ Bulk Operations")
        info_layout = QVBoxLayout(info_box)
        info_text = QLabel(
            "Safely delete multiple documents at once:\n\n"
            "1. Select filter criteria (document type, metadata, etc.)\n"
            "2. Preview what will be deleted\n"
            "3. Export backup (recommended!)\n"
            "4. Delete documents\n"
            "5. Undo if needed (restore from backup)\n\n"
            "⚠️ Always export a backup before deleting!"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_box)
        
        # Filter selection
        filter_group = QGroupBox("🔍 Filter Criteria (All filters combined with AND)")
        filter_layout = QVBoxLayout(filter_group)
        
        # Document type filter with refresh button
        type_layout = QHBoxLayout()
        type_label = QLabel("Document Type:")
        type_label.setMinimumWidth(120)
        type_layout.addWidget(type_label)
        
        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItem("")  # Empty = all types
        self.type_combo.setPlaceholderText("Select or enter type...")
        self.type_combo.setToolTip("Filter by document type. Leave empty for all types.")
        type_layout.addWidget(self.type_combo, 1)
        
        refresh_types_btn = QPushButton("🔄 Refresh Types")
        refresh_types_btn.clicked.connect(self.load_document_types)
        refresh_types_btn.setToolTip("Load document types from database")
        type_layout.addWidget(refresh_types_btn)
        filter_layout.addLayout(type_layout)
        
        # Path/Name filter with wildcards
        path_layout = QHBoxLayout()
        path_label = QLabel("Path/Name Filter:")
        path_label.setMinimumWidth(120)
        path_layout.addWidget(path_label)
        
        self.path_filter = QLineEdit()
        self.path_filter.setPlaceholderText("e.g., *resume*, C:\\Projects\\*, */2024/*")
        self.path_filter.setToolTip("Use wildcards: * for any characters, ? for single character")
        path_layout.addWidget(self.path_filter)
        filter_layout.addLayout(path_layout)
        
        # Additional metadata filters (key-value pairs)
        metadata_label = QLabel("Additional Metadata Filters:")
        metadata_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        filter_layout.addWidget(metadata_label)
        
        # Metadata key 1
        meta1_layout = QHBoxLayout()
        meta1_layout.addWidget(QLabel("Key:"))
        self.meta_key1 = QLineEdit()
        self.meta_key1.setPlaceholderText("e.g., author, department, status")
        meta1_layout.addWidget(self.meta_key1)
        meta1_layout.addWidget(QLabel("Value:"))
        self.meta_value1 = QLineEdit()
        self.meta_value1.setPlaceholderText("e.g., John, HR, obsolete")
        meta1_layout.addWidget(self.meta_value1)
        filter_layout.addLayout(meta1_layout)
        
        # Metadata key 2
        meta2_layout = QHBoxLayout()
        meta2_layout.addWidget(QLabel("Key:"))
        self.meta_key2 = QLineEdit()
        self.meta_key2.setPlaceholderText("e.g., year, category")
        meta2_layout.addWidget(self.meta_key2)
        meta2_layout.addWidget(QLabel("Value:"))
        self.meta_value2 = QLineEdit()
        self.meta_value2.setPlaceholderText("e.g., 2023, draft")
        meta2_layout.addWidget(self.meta_value2)
        filter_layout.addLayout(meta2_layout)
        
        layout.addWidget(filter_group)
        
        # Load document types on init
        self.load_document_types()
        
        # Action buttons
        button_group = QGroupBox("⚡ Actions")
        button_layout = QVBoxLayout(button_group)
        
        # Preview button
        preview_btn_layout = QHBoxLayout()
        self.preview_btn = QPushButton("👁️ Preview Delete")
        self.preview_btn.clicked.connect(self.preview_delete)
        self.preview_btn.setStyleSheet("background-color: #3498db; color: white; padding: 10px; font-weight: bold;")
        preview_btn_layout.addWidget(self.preview_btn)
        button_layout.addLayout(preview_btn_layout)
        
        # Export and Delete buttons (side by side)
        action_btn_layout = QHBoxLayout()
        
        self.export_btn = QPushButton("💾 Export Backup")
        self.export_btn.clicked.connect(self.export_backup)
        self.export_btn.setStyleSheet("background-color: #2ecc71; color: white; padding: 10px; font-weight: bold;")
        self.export_btn.setEnabled(False)
        action_btn_layout.addWidget(self.export_btn)
        
        self.delete_btn = QPushButton("🗑️ Delete Documents")
        self.delete_btn.clicked.connect(self.delete_documents)
        self.delete_btn.setStyleSheet("background-color: #e74c3c; color: white; padding: 10px; font-weight: bold;")
        self.delete_btn.setEnabled(False)
        action_btn_layout.addWidget(self.delete_btn)
        
        button_layout.addLayout(action_btn_layout)
        
        # Undo button
        undo_btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("↩️ Undo Last Delete (Restore)")
        self.undo_btn.clicked.connect(self.undo_delete)
        self.undo_btn.setStyleSheet("background-color: #f39c12; color: white; padding: 10px; font-weight: bold;")
        self.undo_btn.setEnabled(False)
        undo_btn_layout.addWidget(self.undo_btn)
        button_layout.addLayout(undo_btn_layout)
        
        layout.addWidget(button_group)
        
        # Preview results table
        results_group = QGroupBox("📋 Preview Results")
        results_layout = QVBoxLayout(results_group)
        
        self.results_label = QLabel("No preview yet. Click 'Preview Delete' to see what will be deleted.")
        self.results_label.setWordWrap(True)
        results_layout.addWidget(self.results_label)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Document ID", "Document Type", "Source URI"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setVisible(False)
        results_layout.addWidget(self.results_table)
        
        layout.addWidget(results_group)
        
        layout.addStretch()
    
    def load_document_types(self):
        """Load document types from database via metadata discovery API."""
        try:
            # Get all values for the 'type' metadata key
            types = self.api_client.get_metadata_values("type")
            
            # Clear and repopulate combo box
            current_text = self.type_combo.currentText()
            self.type_combo.clear()
            self.type_combo.addItem("")  # Empty option
            
            for doc_type in sorted(types):
                if doc_type:  # Skip empty strings
                    self.type_combo.addItem(doc_type)
            
            # Restore previous selection if it still exists
            if current_text:
                index = self.type_combo.findText(current_text)
                if index >= 0:
                    self.type_combo.setCurrentIndex(index)
            
            logger.info(f"Loaded {len(types)} document types from database")
        except Exception as e:
            logger.error(f"Failed to load document types: {e}")
            # Keep default types if API fails
    
    def get_filters(self):
        """Build filter dictionary from UI inputs."""
        filters = {}
        
        # Document type filter
        doc_type = self.type_combo.currentText().strip()
        if doc_type:
            filters["type"] = doc_type
        
        # Path/name filter with wildcards
        path_filter = self.path_filter.text().strip()
        if path_filter:
            # Convert wildcards to SQL LIKE pattern
            # * -> %, ? -> _
            sql_pattern = path_filter.replace('*', '%').replace('?', '_')
            filters["source_uri_like"] = sql_pattern
        
        # Additional metadata filters
        if self.meta_key1.text().strip() and self.meta_value1.text().strip():
            key = self.meta_key1.text().strip()
            value = self.meta_value1.text().strip()
            filters[f"metadata.{key}"] = value
        
        if self.meta_key2.text().strip() and self.meta_value2.text().strip():
            key = self.meta_key2.text().strip()
            value = self.meta_value2.text().strip()
            filters[f"metadata.{key}"] = value
        
        if not filters:
            QMessageBox.warning(
                self,
                "No Filters",
                "Please select at least one filter criterion."
            )
            return None
        
        return filters
    
    def preview_delete(self):
        """Preview what documents will be deleted."""
        filters = self.get_filters()
        if not filters:
            return
        
        try:
            # Call preview API
            response = self.api_client.bulk_delete_preview(filters)
            
            if response.get("document_count", 0) == 0:
                self.results_label.setText("✅ No documents match the filter criteria.")
                self.results_table.setVisible(False)
                self.export_btn.setEnabled(False)
                self.delete_btn.setEnabled(False)
                return
            
            # Show results
            count = response["document_count"]
            samples = response.get("sample_documents", [])
            
            self.results_label.setText(
                f"⚠️ {count} document(s) will be deleted!\n"
                f"Showing first {len(samples)} documents:"
            )
            
            # Populate table
            self.results_table.setRowCount(len(samples))
            for i, doc in enumerate(samples):
                self.results_table.setItem(i, 0, QTableWidgetItem(doc.get("document_id", "")))
                # Extract document_type from metadata
                metadata = doc.get("metadata", {})
                doc_type = metadata.get("type", "Unknown") if isinstance(metadata, dict) else "Unknown"
                self.results_table.setItem(i, 1, QTableWidgetItem(doc_type))
                self.results_table.setItem(i, 2, QTableWidgetItem(doc.get("source_uri", "")))
            
            self.results_table.setVisible(True)
            self.export_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Preview Failed",
                f"Failed to preview delete:\n{str(e)}"
            )
    
    def export_backup(self):
        """Export documents as backup before deleting."""
        filters = self.get_filters()
        if not filters:
            return
        
        # Ask where to save
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Backup File",
            str(Path.home() / "documents_backup.json"),
            "JSON Files (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            # Export documents
            response = self.api_client.export_documents(filters)
            
            # Save to file
            with open(file_path, 'w') as f:
                json.dump(response, f, indent=2)
            
            # Store for undo
            self.last_backup = response
            self.undo_btn.setEnabled(True)
            
            QMessageBox.information(
                self,
                "Backup Saved",
                f"✅ Backup saved successfully!\n\n"
                f"File: {file_path}\n"
                f"Documents: {response.get('document_count', 0)}\n"
                f"Chunks: {response.get('chunk_count', 0)}\n\n"
                f"You can now safely delete these documents."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export backup:\n{str(e)}"
            )
    
    def delete_documents(self):
        """Actually delete the documents."""
        filters = self.get_filters()
        if not filters:
            return
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "⚠️ Are you sure you want to delete these documents?\n\n"
            "This action cannot be undone unless you have a backup!\n\n"
            "Have you exported a backup?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # Delete documents
            response = self.api_client.bulk_delete(filters)
            
            chunks_deleted = response.get("chunks_deleted", 0)
            
            QMessageBox.information(
                self,
                "Delete Complete",
                f"✅ Successfully deleted {chunks_deleted} chunk(s)!\n\n"
                f"You can undo this if you have a backup."
            )
            
            # Clear preview
            self.results_label.setText("Delete complete. Click 'Preview Delete' to check again.")
            self.results_table.setVisible(False)
            self.export_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Failed to delete documents:\n{str(e)}"
            )
    
    def undo_delete(self):
        """Restore documents from last backup (undo)."""
        if not self.last_backup:
            # Try to load from file
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Backup File",
                str(Path.home()),
                "JSON Files (*.json)"
            )
            
            if not file_path:
                return
            
            try:
                with open(file_path, 'r') as f:
                    self.last_backup = json.load(f)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Load Failed",
                    f"Failed to load backup file:\n{str(e)}"
                )
                return
        
        # Confirm restore
        reply = QMessageBox.question(
            self,
            "Confirm Restore",
            f"Restore {self.last_backup.get('document_count', 0)} document(s) from backup?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # Restore documents
            backup_data = self.last_backup.get("backup_data", [])
            response = self.api_client.restore_documents(backup_data)
            
            chunks_restored = response.get("chunks_restored", 0)
            
            QMessageBox.information(
                self,
                "Restore Complete",
                f"✅ Successfully restored {chunks_restored} chunk(s)!"
            )
            
            # Clear backup
            self.last_backup = None
            self.undo_btn.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Restore Failed",
                f"Failed to restore documents:\n{str(e)}"
            )
