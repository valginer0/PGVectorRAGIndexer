"""
Manage Documents tab for bulk operations (delete, export, restore).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QTextEdit, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt
import json
from pathlib import Path


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
        filter_group = QGroupBox("🔍 Filter Criteria")
        filter_layout = QVBoxLayout(filter_group)
        
        # Document type filter
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Document Type:"))
        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItems([
            "",  # Empty = all types
            "policy",
            "resume",
            "report",
            "memo",
            "draft",
            "final",
            "temp",
            "archive"
        ])
        self.type_combo.setPlaceholderText("Select or enter type...")
        type_layout.addWidget(self.type_combo)
        filter_layout.addLayout(type_layout)
        
        # Metadata filter (advanced)
        metadata_layout = QHBoxLayout()
        metadata_layout.addWidget(QLabel("Custom Filter (JSON):"))
        self.metadata_input = QTextEdit()
        self.metadata_input.setPlaceholderText('{"metadata.author": "John", "metadata.status": "obsolete"}')
        self.metadata_input.setMaximumHeight(60)
        metadata_layout.addWidget(self.metadata_input)
        filter_layout.addLayout(metadata_layout)
        
        layout.addWidget(filter_group)
        
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
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["Document ID", "Source URI"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.setVisible(False)
        results_layout.addWidget(self.results_table)
        
        layout.addWidget(results_group)
        
        layout.addStretch()
    
    def get_filters(self):
        """Build filter dictionary from UI inputs."""
        filters = {}
        
        # Document type filter
        doc_type = self.type_combo.currentText().strip()
        if doc_type:
            filters["type"] = doc_type
        
        # Custom metadata filters
        metadata_json = self.metadata_input.toPlainText().strip()
        if metadata_json:
            try:
                custom_filters = json.loads(metadata_json)
                filters.update(custom_filters)
            except json.JSONDecodeError:
                QMessageBox.warning(
                    self,
                    "Invalid JSON",
                    "Custom filter is not valid JSON. Please fix it or leave empty."
                )
                return None
        
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
                self.results_table.setItem(i, 1, QTableWidgetItem(doc.get("source_uri", "")))
            
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
