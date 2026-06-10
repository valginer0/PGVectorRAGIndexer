"""
Documents tab for viewing and managing indexed documents.
"""

import logging
import sys
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
import math
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QGroupBox, QMenu, QComboBox,
    QTreeView, QStackedWidget,
)
import qtawesome as qta
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QThread, Signal, QPoint, QSignalBlocker, QSize
from .workers import DocumentsWorker, DeleteWorker, TreeStatsWorker
from .document_tree_model import DocumentTreeModel


# ... imports ...

class DocumentsTab(QWidget):
    """Tab for managing documents."""
    
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._lancedb_available = True
        self.source_manager: Optional[object] = None
        self.documents_worker = None
        self.delete_worker = None
        self.current_documents = []
        self.page_size_options = [25, 50, 100]
        self.page_size = self.page_size_options[0]
        self.current_offset = 0
        self._pending_offset = 0
        self.total_documents = 0
        self.total_estimated = False
        self.sort_fields: List[str] = ["indexed_at"]
        self.sort_directions: List[str] = ["desc"]
        self.is_loading = False
        self._view_mode = "tree"  # "list" or "tree"
        self._polling_timer = None
        self.sort_column_mapping = {
            0: "source_uri",
            1: "document_type",
            2: "chunk_count",
            3: "indexed_at",
            4: "last_updated",
        }
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title and refresh button
        header_layout = QHBoxLayout()
        title = QLabel("Document Library")
        title.setProperty("class", "header")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # View toggle buttons
        self._tree_btn = QPushButton(" Tree")
        self._tree_btn.setIcon(qta.icon('fa5s.sitemap', color='#6366f1'))
        self._tree_btn.setStyleSheet("border: 2px solid #6366f1; padding: 6px 12px;")
        self._tree_btn.clicked.connect(lambda: self._set_view_mode("tree"))
        header_layout.addWidget(self._tree_btn)

        self._list_btn = QPushButton(" List")
        self._list_btn.setIcon(qta.icon('fa5s.list', color='white'))
        self._list_btn.setStyleSheet("padding: 6px 12px;")
        self._list_btn.clicked.connect(lambda: self._set_view_mode("list"))
        header_layout.addWidget(self._list_btn)

        # Database source selector (Postgres View vs LanceDB View)
        from PySide6.QtWidgets import QListView
        self.db_source_combo = QComboBox()
        self.db_source_combo.setView(QListView())
        self.db_source_combo.addItem("LanceDB View", "lancedb")
        self.db_source_combo.addItem("Postgres View", "postgres")
        self.db_source_combo.currentIndexChanged.connect(self._on_db_source_changed)
        self.db_source_combo.setStyleSheet(
            "padding: 6px; font-weight: bold; border: 1px solid #374151; "
            "color: #f9fafb; background-color: #1f2937;"
        )
        header_layout.addWidget(self.db_source_combo)

        # Index comparison panel
        from PySide6.QtWidgets import QGroupBox
        self.comparison_group = QGroupBox("Index comparison")
        self.comparison_group.setObjectName("indexComparisonGroup")
        self.comparison_group.setStyleSheet(
            "QGroupBox { border: 1px solid #374151; border-radius: 6px; "
            "margin-top: 0px; padding: 5px; font-weight: bold; color: #6366f1; }"
            "QLabel { font-size: 12px; font-weight: bold; color: #9ca3af; }"
        )
        comp_layout = QVBoxLayout(self.comparison_group)
        comp_layout.setSpacing(2)
        comp_layout.setContentsMargins(5, 5, 5, 5)

        self.pg_stats_label = QLabel("Postgres : -")
        self.ldb_stats_label = QLabel("LanceDB  : -")
        self.status_stats_label = QLabel("Status   : -")

        comp_layout.addWidget(self.pg_stats_label)
        comp_layout.addWidget(self.ldb_stats_label)
        comp_layout.addWidget(self.status_stats_label)

        header_layout.addWidget(self.comparison_group)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='white'))
        self.refresh_btn.clicked.connect(self._refresh_current_view)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        
        # Stacked widget to switch between list and tree views
        self._view_stack = QStackedWidget()

        # --- Page 0: List view ---
        list_page = QWidget()
        list_page_layout = QVBoxLayout(list_page)
        list_page_layout.setContentsMargins(0, 0, 0, 0)

        table_group = QGroupBox("Indexed Documents")
        table_layout = QVBoxLayout(table_group)

        self.documents_table = QTableWidget()
        self.documents_table.setColumnCount(6)
        self.documents_table.setHorizontalHeaderLabels([
            "Source URI", "Type", "Chunks", "Created", "Updated", "Actions"
        ])
        self.documents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        header = self.documents_table.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.handle_header_clicked)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(3, Qt.DescendingOrder)
        self.documents_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.documents_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.documents_table.cellClicked.connect(self.handle_documents_cell_clicked)
        self.documents_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.documents_table.customContextMenuRequested.connect(self.show_documents_context_menu)
        self.documents_table.viewport().setCursor(Qt.PointingHandCursor)
        table_layout.addWidget(self.documents_table)
        
        pagination_layout = QHBoxLayout()
        page_size_label = QLabel("Rows per page:")
        pagination_layout.addWidget(page_size_label)
        
        self.page_size_combo = QComboBox()
        self.page_size_combo.setView(QListView())
        for size in self.page_size_options:
            self.page_size_combo.addItem(str(size))
        with QSignalBlocker(self.page_size_combo):
            index = self.page_size_combo.findText(str(self.page_size))
            if index != -1:
                self.page_size_combo.setCurrentIndex(index)
        self.page_size_combo.currentIndexChanged.connect(self.on_page_size_changed)
        self.page_size_combo.setMinimumHeight(35)  # Prevent crushing at min window height
        pagination_layout.addWidget(self.page_size_combo)
        pagination_layout.addStretch()
        
        self.prev_page_btn = QPushButton("Previous")
        self.prev_page_btn.setIcon(qta.icon('fa5s.chevron-left', color='white'))
        self.prev_page_btn.clicked.connect(lambda: self.change_page(-1))
        self.prev_page_btn.setEnabled(False)
        pagination_layout.addWidget(self.prev_page_btn)
        
        self.next_page_btn = QPushButton("Next")
        self.next_page_btn.setIcon(qta.icon('fa5s.chevron-right', color='white'))
        self.next_page_btn.setLayoutDirection(Qt.RightToLeft) # Icon on right
        self.next_page_btn.clicked.connect(lambda: self.change_page(1))
        self.next_page_btn.setEnabled(False)
        pagination_layout.addWidget(self.next_page_btn)
        
        list_page_layout.addWidget(table_group)
        list_page_layout.addLayout(pagination_layout)

        # --- Page 1: Tree view ---
        tree_page = QWidget()
        tree_page_layout = QVBoxLayout(tree_page)
        tree_page_layout.setContentsMargins(0, 0, 0, 0)

        tree_group = QGroupBox("Document Tree")
        tree_group_layout = QVBoxLayout(tree_group)

        self._tree_model = DocumentTreeModel(self.api_client)
        self._tree_model.loading.connect(self._on_tree_loading)
        self._tree_model.loaded.connect(self._on_tree_loaded)
        self._tree_model.load_failed.connect(self._on_tree_load_failed)

        self._doc_tree = QTreeView()
        self._doc_tree.setModel(self._tree_model)
        tree_header = self._doc_tree.header()
        tree_header.setStretchLastSection(False)
        tree_header.setSectionResizeMode(0, QHeaderView.Stretch)
        tree_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tree_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tree_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._doc_tree.setSelectionBehavior(QTreeView.SelectRows)
        self._doc_tree.setEditTriggers(QTreeView.NoEditTriggers)
        self._doc_tree.doubleClicked.connect(self._on_tree_item_double_clicked)
        self._doc_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._doc_tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        tree_group_layout.addWidget(self._doc_tree)

        tree_page_layout.addWidget(tree_group)

        # Add pages to stack in UI priority order: tree first, then list.
        self._view_stack.addWidget(tree_page)   # index 0
        self._view_stack.addWidget(list_page)   # index 1

        layout.addWidget(self._view_stack)

        # Status label
        self.status_label = QLabel("Click Refresh to load documents")
        self.status_label.setProperty("class", "subtitle")
        layout.addWidget(self.status_label)

        # Auto-load on first show - DEFERRED to MainWindow
        # self.load_documents()
    
    def load_documents(self, *, reset_offset: bool = False):
        """Load the list of documents."""
        if reset_offset:
            self.current_offset = 0
        
        if self.is_loading:
            return
        health = self.api_client.get_health()
        if health.get("status") == "initializing":
            self.status_label.setText("Backend is initializing models. Please wait...")
            self.status_label.setStyleSheet("color: #f59e0b; font-style: italic;")
            return
            
        if health.get("status") == "unreachable":
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not reachable. Please make sure Docker containers are running."
            )
            return
        
        # Disable UI during load
        self.refresh_btn.setEnabled(False)
        self.page_size_combo.setEnabled(False)
        self.prev_page_btn.setEnabled(False)
        self.next_page_btn.setEnabled(False)
        self.status_label.setText("Loading documents...")
        self.status_label.setStyleSheet("color: #6366f1; font-style: italic;")
        self.is_loading = True
        
        params = {
            "limit": self.page_size,
            "offset": self.current_offset,
            "sort_by": ",".join(self.sort_fields),
            "sort_dir": ",".join(self.sort_directions),
        }
        
        # Track the offset we asked the backend for so we can reconcile with the payload
        self._pending_offset = params["offset"]

        # Start worker
        self.documents_worker = DocumentsWorker(self.api_client, params)
        self.documents_worker.finished.connect(self.documents_loaded)
        self.documents_worker.start()
    
    def documents_loaded(self, success: bool, data):
        """Handle documents load completion."""
        # Re-enable UI
        self.refresh_btn.setEnabled(True)
        self.page_size_combo.setEnabled(True)
        self.is_loading = False
        
        if success:
            payload = data
            if isinstance(payload, list):
                payload = {
                    "items": payload,
                    "total": len(payload),
                    "limit": self.page_size,
                    "offset": self._pending_offset,
                    "sort": {
                        "by": ",".join(self.sort_fields),
                        "direction": ",".join(self.sort_directions),
                    },
                    "_total_estimated": True,
                }
            
            items = payload.get("items", [])
            total = payload.get("total", len(items))
            limit = payload.get("limit", self.page_size)
            offset = payload.get("offset", self._pending_offset)
            if offset != self._pending_offset:
                offset = self._pending_offset
            estimated = bool(payload.get("_total_estimated", False))

            if estimated:
                total = max(total, offset + len(items))

            if estimated and offset > 0 and not items:
                # Revert to previous page if we overshoot total
                self.current_offset = max(0, offset - max(1, limit))
                self.load_documents()
                return
            
            if not estimated and total > 0 and offset >= total and offset != 0:
                # Requested page beyond total, move back and reload
                max_page_offset = max(0, (math.ceil(total / max(limit, 1)) - 1) * max(limit, 1))
                if max_page_offset != self.current_offset:
                    self.current_offset = max_page_offset
                    self.load_documents()
                    return
            
            self.total_documents = total
            self.total_estimated = estimated
            self.page_size = max(1, limit)
            self.current_offset = max(0, offset)
            
            if self.page_size not in self.page_size_options:
                self.page_size_options.append(self.page_size)
                self.page_size_options.sort()
                with QSignalBlocker(self.page_size_combo):
                    self.page_size_combo.clear()
                    for size in self.page_size_options:
                        self.page_size_combo.addItem(str(size))
            
            with QSignalBlocker(self.page_size_combo):
                index = self.page_size_combo.findText(str(self.page_size))
                if index != -1:
                    self.page_size_combo.setCurrentIndex(index)

            self.current_documents = items
            # Always refresh table contents to avoid stale column data after sorting
            self.documents_table.setSortingEnabled(False)
            self.display_documents(items)
            self.documents_table.setSortingEnabled(True)
            self.update_pagination_state(item_count=len(items))
        else:
            error_msg = data
            if isinstance(error_msg, dict) and "detail" in error_msg:
                error_msg = error_msg["detail"]
            QMessageBox.critical(self, "Load Failed", f"Failed to load documents: {error_msg}")
            self.status_label.setText("Load failed")
            self.status_label.setStyleSheet("color: #ef4444; font-style: italic;")
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
    
    def display_documents(self, documents: List[Dict[str, Any]]):
        """Display documents in the table."""
        self.documents_table.setRowCount(len(documents))
        
        for i, doc in enumerate(documents):
            # Source URI (document_id stored for context-menu actions)
            source_item = self._create_source_item(doc.get('source_uri', ''))
            source_item.setData(Qt.UserRole + 1, doc.get('document_id'))
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
            delete_btn = QPushButton("Delete")
            delete_btn.setIcon(qta.icon('fa5s.trash-alt', color='white'))
            delete_btn.setProperty("class", "danger")
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
            self.status_label.setStyleSheet("color: #6366f1; font-style: italic;")
            
            # Start delete worker
            self.delete_worker = DeleteWorker(self.api_client, document_id)
            self.delete_worker.finished.connect(self.delete_finished)
            self.delete_worker.start()
    
    def delete_finished(self, success: bool, message: str):
        """Handle delete completion."""
        if success:
            QMessageBox.information(self, "Success", message)
            # Reload documents
            if self.total_documents > 0 and len(self.current_documents) <= 1 and self.current_offset > 0:
                self.current_offset = max(0, self.current_offset - self.page_size)
            self.load_documents()
        else:
            QMessageBox.critical(self, "Delete Failed", f"Failed to delete document: {message}")
            self.status_label.setText("Delete failed")
            self.status_label.setStyleSheet("color: #ef4444; font-style: italic;")

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
            item.setForeground(QColor("#6366f1"))
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

        entry = self.source_manager.find_entry(source_uri)
        queued = entry.queued if entry else False
        queue_label = "Unqueue from Reindex" if queued else "Queue for Reindex"
        queue_action = menu.addAction(queue_label)

        reindex_action = menu.addAction("Reindex Now")
        remove_action = menu.addAction("Remove from Recent")

        document_id = item.data(Qt.UserRole + 1)
        make_private_action = None
        make_shared_action = None
        if document_id:
            menu.addSeparator()
            make_private_action = menu.addAction("Make Private")
            make_shared_action = menu.addAction("Make Shared")

        action = menu.exec(self.documents_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if document_id and action == make_private_action:
            self.set_document_visibility(document_id, "private")
            return
        if document_id and action == make_shared_action:
            self.set_document_visibility(document_id, "shared")
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

    def set_document_visibility(self, document_id: str, visibility: str) -> None:
        """Set a document's visibility via the backend (shared/private)."""
        try:
            self.api_client.set_document_visibility(document_id, visibility=visibility)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Visibility Change Failed",
                f"Could not set the document to {visibility}:\n{exc}",
            )
            return

        if visibility == "private":
            owner_id = None
            try:
                info = self.api_client.get_document_visibility(document_id) or {}
                owner_id = info.get("owner_id")
            except Exception:
                pass
            if not owner_id:
                QMessageBox.information(
                    self,
                    "Private — Owner Needed",
                    "The document is marked private, but it has no owner yet, "
                    "so it remains visible to everyone.\n\n"
                    "Documents uploaded while signed in get an owner "
                    "automatically; for existing documents an admin can assign "
                    "one via the ownership transfer API.",
                )
                return

        self.status_label.setText(f"Document set to {visibility}")
        self.status_label.setStyleSheet("color: #22c55e; font-style: italic;")

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

    def on_page_size_changed(self, index: int) -> None:
        if index < 0:
            return
        try:
            new_size = int(self.page_size_combo.itemText(index))
        except ValueError:
            return
        if new_size == self.page_size:
            return
        self.page_size = new_size
        self.current_offset = 0
        self.load_documents()

    def change_page(self, step: int) -> None:
        if step == 0 or self.page_size <= 0:
            return
        new_offset = self.current_offset + (step * self.page_size)
        new_offset = max(0, new_offset)
        if not self.total_estimated and self.total_documents and new_offset >= self.total_documents:
            return
        if new_offset == self.current_offset:
            return
        self.current_offset = new_offset
        self.load_documents()

    def update_pagination_state(self, item_count: int) -> None:
        if self.total_documents == 0 and item_count == 0:
            self.status_label.setText("No documents found")
            self.status_label.setStyleSheet("color: #666; font-style: italic;")
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
            return
        start_index = self.current_offset + 1
        end_index = self.current_offset + item_count
        page_number = (self.current_offset // self.page_size) + 1 if self.page_size else 1
        if self.total_estimated:
            total_display = f"≥{self.total_documents}" if self.total_documents else "unknown"
            pages_text = f"Page {page_number}"
            self.status_label.setText(
                f"Showing {start_index}-{end_index} of {total_display} documents ({pages_text})"
            )
            has_next = item_count >= self.page_size
        else:
            total_pages = max(1, math.ceil(self.total_documents / self.page_size)) if self.page_size else 1
            self.status_label.setText(
                f"Showing {start_index}-{end_index} of {self.total_documents} documents (Page {page_number} of {total_pages})"
            )
            has_next = end_index < self.total_documents
        self.status_label.setStyleSheet("color: #10b981; font-style: italic;")
        self.prev_page_btn.setEnabled(self.current_offset > 0)
        self.next_page_btn.setEnabled(has_next)

    def handle_header_clicked(self, section: int) -> None:
        field = self.sort_column_mapping.get(section)
        if not field:
            return
        current_field = self.sort_fields[0] if self.sort_fields else None
        if current_field == field:
            self.sort_directions[0] = "asc" if self.sort_directions[0] == "desc" else "desc"
        else:
            self.sort_fields = [field]
            self.sort_directions = [self._default_sort_direction(field)]
        header = self.documents_table.horizontalHeader()
        order = Qt.AscendingOrder if self.sort_directions[0] == "asc" else Qt.DescendingOrder
        header.setSortIndicator(section, order)
        self.load_documents(reset_offset=True)

    def _default_sort_direction(self, field: str) -> str:
        if field in {"chunk_count", "indexed_at", "last_updated"}:
            return "desc"
        return "asc"

    # ------------------------------------------------------------------
    # View toggle
    # ------------------------------------------------------------------

    def _set_view_mode(self, mode: str) -> None:
        """Switch between 'list' and 'tree' view."""
        self._view_mode = mode
        _active = "border: 2px solid #6366f1; padding: 6px 12px;"
        _inactive = "padding: 6px 12px;"
        if mode == "list":
            self._view_stack.setCurrentIndex(1)
            self._list_btn.setStyleSheet(_active)
            self._list_btn.setIcon(qta.icon('fa5s.list', color='#6366f1'))
            self._tree_btn.setStyleSheet(_inactive)
            self._tree_btn.setIcon(qta.icon('fa5s.sitemap', color='white'))
            self.db_source_combo.setVisible(False)
            self.comparison_group.setVisible(False)
            self._stop_polling_timer()
        else:
            self._view_stack.setCurrentIndex(0)
            self._tree_btn.setStyleSheet(_active)
            self._tree_btn.setIcon(qta.icon('fa5s.sitemap', color='#6366f1'))
            self._list_btn.setStyleSheet(_inactive)
            self._list_btn.setIcon(qta.icon('fa5s.list', color='white'))
            self.db_source_combo.setVisible(self._lancedb_available)
            self.comparison_group.setVisible(True)
            if not self._tree_model.is_initialized():
                self._tree_model.load_root()
            self._load_tree_stats()

    def _refresh_current_view(self) -> None:
        """Refresh whichever view is currently active."""
        if self._view_mode == "tree":
            self._tree_model.refresh()
            self._load_tree_stats()
        else:
            self.load_documents()

    def _on_db_source_changed(self, index: int) -> None:
        """Handle database source change."""
        source = self.db_source_combo.itemData(index)
        self._tree_model.set_source(source)
        self._load_tree_stats()

    def _load_tree_stats(self) -> None:
        """Load tree statistics for comparison."""
        self.status_stats_label.setText("Status   : comparing...")
        self.status_stats_label.setStyleSheet("color: #9ca3af; font-weight: bold;")
        self.tree_stats_worker = TreeStatsWorker(self.api_client)
        self.tree_stats_worker.finished.connect(self._on_tree_stats_loaded)
        self.tree_stats_worker.start()

    def _on_tree_stats_loaded(self, success: bool, data: Any) -> None:
        """Handle tree stats loaded."""
        if success and data:
            pg = data.get("postgres", {})
            ldb = data.get("lancedb", {})
            pg_docs = pg.get("total_documents", 0)
            pg_chunks = pg.get("total_chunks", 0)
            
            self.pg_stats_label.setText(f"Postgres : {pg_docs} docs / {pg_chunks} chunks")
            
            if ldb is None:
                self._lancedb_available = False
                self.db_source_combo.setVisible(False)
                postgres_index = self.db_source_combo.findData("postgres")
                if postgres_index >= 0:
                    self.db_source_combo.setCurrentIndex(postgres_index)
                self._tree_model.set_source("postgres")
                self.ldb_stats_label.setVisible(False)
                self.status_stats_label.setVisible(False)
                self._stop_polling_timer()
            else:
                if not self._lancedb_available:
                    self._lancedb_available = True
                    self.db_source_combo.setVisible(self._view_mode == "tree")
                    lancedb_index = self.db_source_combo.findData("lancedb")
                    if lancedb_index >= 0:
                        self.db_source_combo.setCurrentIndex(lancedb_index)
                        self._tree_model.set_source("lancedb")
                else:
                    self.db_source_combo.setVisible(self._view_mode == "tree")
                ldb_docs = ldb.get("total_documents", 0)
                ldb_chunks = ldb.get("total_chunks", 0)
                self.ldb_stats_label.setText(f"LanceDB  : {ldb_docs} docs / {ldb_chunks} chunks")
                self.ldb_stats_label.setVisible(True)
                self.status_stats_label.setVisible(True)
                
                # Determine sync status
                if pg_docs == ldb_docs and pg_chunks == ldb_chunks:
                    self.status_stats_label.setText("Status   : ✓ in sync")
                    self.status_stats_label.setStyleSheet("color: #10b981; font-weight: bold;")
                    self._stop_polling_timer()
                elif ldb_docs < pg_docs or (pg_docs == ldb_docs and ldb_chunks < pg_chunks):
                    self.status_stats_label.setText("Status   : ⟳ syncing — LanceDB behind")
                    self.status_stats_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
                    if self._view_mode == "tree":
                        self._start_polling_timer()
                else:
                    self.status_stats_label.setText("Status   : counts differ")
                    self.status_stats_label.setStyleSheet("color: #9ca3af; font-weight: bold;")
                    self._stop_polling_timer()

    def _start_polling_timer(self) -> None:
        """Start polling stats every ~4s if active and not already running."""
        from PySide6.QtCore import QTimer
        if self._polling_timer is None:
            self._polling_timer = QTimer(self)
            self._polling_timer.setInterval(4000)
            self._polling_timer.timeout.connect(self._load_tree_stats)
        if not self._polling_timer.isActive():
            self._polling_timer.start()

    def _stop_polling_timer(self) -> None:
        """Stop the stats polling timer."""
        if self._polling_timer and self._polling_timer.isActive():
            self._polling_timer.stop()

    def hideEvent(self, event) -> None:
        self._stop_polling_timer()
        super().hideEvent(event)


    # ------------------------------------------------------------------
    # Tree view signals
    # ------------------------------------------------------------------

    def _on_tree_loading(self, parent_path: str) -> None:
        if self._view_mode != "tree":
            return
        self.status_label.setText("Loading tree...")
        self.status_label.setStyleSheet("color: #6366f1; font-style: italic;")

    def _on_tree_loaded(self, parent_path: str, child_count: int) -> None:
        if self._view_mode != "tree":
            return
        if parent_path:
            self.status_label.setText(f"{parent_path}: {child_count} items")
        else:
            self.status_label.setText(f"Document tree loaded ({child_count} top-level items)")
        self.status_label.setStyleSheet("color: #10b981; font-style: italic;")

    def _on_tree_load_failed(self, error: str) -> None:
        if self._view_mode != "tree":
            return
        self.status_label.setText(f"Tree load failed: {error}")
        self.status_label.setStyleSheet("color: #ef4444; font-style: italic;")

    def _on_tree_item_double_clicked(self, index) -> None:
        """Open a file when double-clicked in tree view."""
        node = self._tree_model.node_for_index(index)
        if node.node_type != "file":
            return
        if node.path:
            if self.source_manager:
                self.source_manager.open_path(node.path)
            else:
                self.open_source_path(node.path)

    def _show_tree_context_menu(self, pos) -> None:
        """Context menu for tree view items."""
        index = self._doc_tree.indexAt(pos)
        if not index.isValid():
            return
        node = self._tree_model.node_for_index(index)
        if node.node_type not in ("file", "folder") or not node.path:
            return

        source_uri = node.path
        menu = QMenu(self)
        copy_path_action = menu.addAction("Copy Path")
        delete_folder_action = None

        if node.node_type == "folder":
            delete_folder_action = menu.addAction("Delete Folder Documents...")

        open_action = open_with_action = show_in_folder_action = None
        queue_action = reindex_action = remove_action = None
        if node.node_type == "file" and self.source_manager:
            open_action = menu.addAction("Open")
            open_with_action = menu.addAction("Open with…")
            show_in_folder_action = menu.addAction("Show in Folder")

            entry = self.source_manager.find_entry(source_uri)
            queued = entry.queued if entry else False
            queue_label = "Unqueue from Reindex" if queued else "Queue for Reindex"
            queue_action = menu.addAction(queue_label)
            reindex_action = menu.addAction("Reindex Now")
            remove_action = menu.addAction("Remove from Recent")

        action = menu.exec(self._doc_tree.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == copy_path_action:
            if node.node_type == "file" and self.source_manager:
                self.source_manager.open_path(source_uri, mode="copy_path", auto_queue=False)
            else:
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(source_uri)
        elif action == delete_folder_action:
            self.delete_folder_documents(source_uri, node.name)
        elif action == open_action:
            self.source_manager.open_path(source_uri)
        elif action == open_with_action:
            self.source_manager.open_path(source_uri, mode="open_with")
        elif action == show_in_folder_action:
            self.source_manager.open_path(source_uri, mode="show_in_folder", auto_queue=False)
        elif action == queue_action:
            self.source_manager.queue_entry(source_uri, not queued)
        elif action == reindex_action:
            self.source_manager.trigger_reindex_path(source_uri)
        elif action == remove_action:
            self.source_manager.remove_entry(source_uri)

    def delete_folder_documents(self, folder_path: str, folder_name: Optional[str] = None) -> None:
        """Delete all documents below a tree folder path."""
        pattern = self._folder_source_uri_like_pattern(folder_path)
        filters = {"source_uri_like": pattern}
        display_name = folder_name or folder_path

        try:
            preview = self.api_client.bulk_delete_preview(filters)
            document_count = int(preview.get("document_count", 0))
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Preview Failed",
                f"Failed to preview folder delete:\n{exc}",
            )
            return

        if document_count <= 0:
            QMessageBox.information(
                self,
                "No Documents Found",
                f"No indexed documents were found under:\n\n{folder_path}",
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirm Folder Delete",
            f"Delete {document_count} indexed document(s) under:\n\n"
            f"{display_name}\n\n"
            "This removes the indexed chunks from the database, not files on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            response = self.api_client.bulk_delete(filters)
            chunks_deleted = response.get("chunks_deleted", 0)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Failed to delete folder documents:\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Delete Complete",
            f"Deleted {chunks_deleted} indexed chunk(s) under:\n\n{folder_path}",
        )
        self._refresh_current_view()

    @staticmethod
    def _folder_source_uri_like_pattern(folder_path: str) -> str:
        """Build a normalized LIKE pattern for all documents below a folder."""
        normalized = (
            folder_path
            .replace('\\', '/')
            .replace('\t', '/')
            .replace('\n', '/')
            .replace('\r', '/')
        )
        while '//' in normalized:
            normalized = normalized.replace('//', '/')
        normalized = normalized.rstrip("/")
        if not normalized:
            return "%"
        return f"{normalized}/%"
