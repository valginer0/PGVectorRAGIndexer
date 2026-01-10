"""
Manage Documents tab for bulk operations (delete, export, restore).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QMessageBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QMenu
)
import qtawesome as qta
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QColor
from typing import Optional

import logging
import sys
import os
import json
import subprocess
from pathlib import Path
from .source_open_manager import SourceOpenManager
from .shared import populate_document_type_combo

logger = logging.getLogger(__name__)

class ManageTab(QWidget):
    """Tab for managing documents (bulk delete, export, restore)."""
    
    def __init__(self, api_client, source_manager: Optional[SourceOpenManager] = None):
        super().__init__()
        self.api_client = api_client
        self.last_backup = None  # Store last backup for undo
        self.source_manager = source_manager
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Manage Documents")
        title.setProperty("class", "header")
        layout.addWidget(title)
        
        # Instructions - simplified to single line
        info_label = QLabel("<b>Bulk Operations:</b> Filter by type/path → Preview → Export Backup → Delete. <span style='color:#f59e0b'>⚠️ Always backup first!</span>")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #9ca3af; padding: 10px; background: #1f2937; border-radius: 5px;")
        layout.addWidget(info_label)
        
        # Filter selection
        filter_group = QGroupBox("Filter Criteria (All filters combined with AND)")
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
        self.type_combo.setMinimumHeight(35)  # Prevent crushing at min window height
        type_layout.addWidget(self.type_combo, 1)
        
        refresh_types_btn = QPushButton()
        refresh_types_btn.setIcon(qta.icon('fa5s.sync-alt', color='#9ca3af'))
        refresh_types_btn.clicked.connect(self.load_document_types)
        refresh_types_btn.setToolTip("Load document types from database")
        refresh_types_btn.setFixedSize(30, 30)
        type_layout.addWidget(refresh_types_btn)
        filter_layout.addLayout(type_layout)
        
        # Path/Name filter with wildcards
        path_layout = QHBoxLayout()
        path_label = QLabel("Path/Name Filter:")
        path_label.setMinimumWidth(120)
        path_layout.addWidget(path_label)
        
        self.path_filter = QLineEdit("*")  # Default to match all
        self.path_filter.setPlaceholderText("e.g., *resume*, C:\\Projects\\*, */2024/*")
        self.path_filter.setToolTip("Use wildcards: * for any characters, ? for single character. Default '*' matches all files.")
        path_layout.addWidget(self.path_filter)
        filter_layout.addLayout(path_layout)
        
        layout.addWidget(filter_group)
        
        # Load document types on init
        self.load_document_types()
        
        # Action buttons
        button_group = QGroupBox("Actions")
        button_layout = QVBoxLayout(button_group)
        
        # Preview button
        preview_btn_layout = QHBoxLayout()
        self.preview_btn = QPushButton("Preview Delete")
        self.preview_btn.setIcon(qta.icon('fa5s.eye', color='white'))
        self.preview_btn.clicked.connect(self.preview_delete)
        self.preview_btn.setProperty("class", "primary")
        preview_btn_layout.addWidget(self.preview_btn)
        button_layout.addLayout(preview_btn_layout)
        
        # Export and Delete buttons (side by side)
        action_btn_layout = QHBoxLayout()
        
        self.export_btn = QPushButton("Export Backup")
        self.export_btn.setIcon(qta.icon('fa5s.save', color='white'))
        self.export_btn.clicked.connect(self.export_backup)
        self.export_btn.setStyleSheet("background-color: #10b981; border: 1px solid #10b981;") # Success color
        self.export_btn.setEnabled(False)
        action_btn_layout.addWidget(self.export_btn)
        
        self.delete_btn = QPushButton("Delete Documents")
        self.delete_btn.setIcon(qta.icon('fa5s.trash-alt', color='white'))
        self.delete_btn.clicked.connect(self.delete_documents)
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.setEnabled(False)
        action_btn_layout.addWidget(self.delete_btn)
        
        button_layout.addLayout(action_btn_layout)
        
        # Undo button
        undo_btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("Undo Last Delete (Restore)")
        self.undo_btn.setIcon(qta.icon('fa5s.undo', color='white'))
        self.undo_btn.clicked.connect(self.undo_delete)
        self.undo_btn.setStyleSheet("background-color: #f59e0b; border: 1px solid #f59e0b;") # Warning color
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
        self.results_table.cellClicked.connect(self.handle_results_cell_clicked)
        self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.show_results_context_menu)
        self.results_table.viewport().setCursor(Qt.PointingHandCursor)
        self.results_table.setVisible(False)
        results_layout.addWidget(self.results_table)
        
        layout.addWidget(results_group)
        
        layout.addStretch()
    
    def load_document_types(self):
        """Load document types from database via metadata discovery API."""
        populate_document_type_combo(
            self.type_combo,
            self.api_client,
            logger,
            log_context="Manage tab"
        )
    
    def get_filters(self):
        """Build filter dictionary from UI inputs."""
        filters = {}
        
        # Document type filter (skip '*' which means match all)
        doc_type = self.type_combo.currentText().strip()
        if doc_type and doc_type != '*':
            filters["type"] = doc_type
        
        # Path/name filter with wildcards
        path_filter = self.path_filter.text().strip()
        if path_filter:
            # Normalize backslashes/control chars to forward slashes before wildcard conversion
            normalized = (
                path_filter
                .replace('\\', '/')
                .replace('\t', '/')
                .replace('\n', '/')
                .replace('\r', '/')
            )
            while '//' in normalized:
                normalized = normalized.replace('//', '/')
            # Convert wildcards: * -> %, ? -> _
            sql_pattern = normalized.replace('*', '%').replace('?', '_')
            filters["source_uri_like"] = sql_pattern
        
        # Additional metadata filters
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
                doc_id_item = QTableWidgetItem(doc.get("document_id", ""))
                doc_id_item.setFlags(doc_id_item.flags() & ~Qt.ItemIsEditable)
                self.results_table.setItem(i, 0, doc_id_item)
                # Extract document_type from metadata
                metadata = doc.get("metadata", {})
                doc_type = metadata.get("type", "Unknown") if isinstance(metadata, dict) else "Unknown"
                type_item = QTableWidgetItem(doc_type)
                type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
                self.results_table.setItem(i, 1, type_item)
                source_item = self._create_source_item(doc.get("source_uri", ""))
                self.results_table.setItem(i, 2, source_item)
            
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
    
    def _create_source_item(self, source_uri: str) -> QTableWidgetItem:
        """Create table item for clickable source URI."""
        display_text = source_uri or ""
        item = QTableWidgetItem(display_text)
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
        if column != 2:
            return

        item = self.results_table.item(row, column)
        if item is None:
            return

        source_uri = item.data(Qt.UserRole) or item.text()
        if self.source_manager:
            self.source_manager.open_path(source_uri)
        else:
            self.open_source_path(source_uri)

    def show_results_context_menu(self, pos: QPoint) -> None:
        if not self.source_manager:
            return

        index = self.results_table.indexAt(pos)
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

    def open_source_path(self, path: str) -> None:
        """Open the given path with the OS default application."""
        if not path:
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
