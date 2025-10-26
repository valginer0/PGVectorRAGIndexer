from __future__ import annotations

from functools import partial
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from .source_open_manager import SourceOpenManager, RecentEntry


class _NoElideDelegate(QStyledItemDelegate):
    """Ensure text is never elided in the Path column."""

    def paint(self, painter, option, index):
        no_elide = QStyleOptionViewItem(option)
        no_elide.textElideMode = Qt.ElideNone
        super().paint(painter, no_elide, index)


class RecentActivityTab(QWidget):
    """Panel showing recently opened documents and reindex queue controls."""

    def __init__(self, source_manager: SourceOpenManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.source_manager = source_manager

        layout = QVBoxLayout(self)

        # Controls row
        controls = QHBoxLayout()
        self.queue_count_label = QLabel()
        controls.addWidget(self.queue_count_label)

        self.status_label = QLabel()
        controls.addWidget(self.status_label)

        controls.addStretch()

        self.process_button = QPushButton("Reindex Queued")
        self.process_button.clicked.connect(self._handle_process_queue)
        controls.addWidget(self.process_button)

        self.clear_queue_button = QPushButton("Clear Queue")
        self.clear_queue_button.clicked.connect(self._handle_clear_queue)
        controls.addWidget(self.clear_queue_button)

        self.clear_list_button = QPushButton("Clear List")
        self.clear_list_button.clicked.connect(self._handle_clear_list)
        controls.addWidget(self.clear_list_button)

        layout.addLayout(controls)

        # Recent entries table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Path",
            "Opened",
            "Queued",
            "Reindexed",
            "Last Error",
            "Actions",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setItemDelegateForColumn(0, _NoElideDelegate(self.table))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        # Wire SourceOpenManager events
        self.source_manager.entry_added.connect(self._handle_entry_added)
        self.source_manager.entry_updated.connect(self._handle_entry_updated)
        self.source_manager.entry_removed.connect(self._handle_entry_removed)
        self.source_manager.entries_cleared.connect(self.table.clearContents)
        self.source_manager.entries_cleared.connect(self._handle_entries_cleared)

        # Load existing entries
        for entry in self.source_manager.get_recent_entries():
            self._upsert_entry(entry)

        self._update_queue_indicator()

    # ------------------------------------------------------------------
    # SourceOpenManager signal handlers
    # ------------------------------------------------------------------
    def _handle_entry_added(self, entry: RecentEntry) -> None:
        self._upsert_entry(entry)
        self._update_queue_indicator()

    def _handle_entry_updated(self, entry: RecentEntry) -> None:
        self._upsert_entry(entry)
        self._update_queue_indicator()

    def _handle_entry_removed(self, entry: RecentEntry) -> None:
        row = self._row_for_path(entry.path)
        if row is not None:
            self.table.removeRow(row)
        self._update_queue_indicator()

    def _handle_entries_cleared(self) -> None:
        self.table.setRowCount(0)
        self._update_queue_indicator()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def _handle_process_queue(self) -> None:
        success, failures = self.source_manager.process_queue()
        if success == 0 and failures == 0:
            self._set_status("No queued documents to reindex.")
        else:
            parts = []
            if success:
                parts.append(f"Reindex requested for {success} document(s).")
            if failures:
                parts.append(f"Failed to queue {failures} document(s).")
            self._set_status(" ".join(parts))
        self._update_queue_indicator()

    def _handle_clear_queue(self) -> None:
        changed = self.source_manager.clear_queue()
        if changed:
            self._set_status("Queue cleared.")
        else:
            self._set_status("Queue already empty.")
        self._update_queue_indicator()

    def _handle_clear_list(self) -> None:
        if self.table.rowCount() == 0:
            self._set_status("Nothing to clear.")
            return
        self.source_manager.clear_entries()
        self._set_status("Recent activity cleared.")

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------
    def _upsert_entry(self, entry: RecentEntry) -> None:
        row = self._row_for_path(entry.path)
        if row is None:
            self.table.insertRow(0)
            row = 0

        self.table.setItem(row, 0, self._item(entry.path, entry.path))
        opened_text = entry.opened_at.strftime("%Y-%m-%d %H:%M:%S")
        self.table.setItem(row, 1, self._item(opened_text))
        self.table.setItem(row, 2, self._item("Yes" if entry.queued else "No"))
        status = "Yes" if entry.reindexed else "No"
        self.table.setItem(row, 3, self._item(status))
        self.table.setItem(row, 4, self._item(entry.last_error or ""))

        actions_widget = self._build_actions_widget(entry.path, entry.queued)
        self.table.setCellWidget(row, 5, actions_widget)

    def _row_for_path(self, path: str) -> Optional[int]:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == path:
                return row
        return None

    def _item(self, text: str, path: Optional[str] = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if path is not None:
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            font = item.font()
            font.setUnderline(True)
            item.setFont(font)
            item.setForeground(QColor("#1a73e8"))
        return item

    def _build_actions_widget(self, path: str, queued: bool) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(partial(self.source_manager.open_path, path, "default", False))
        layout.addWidget(open_btn)

        queue_btn = QPushButton("Unqueue" if queued else "Queue")
        queue_btn.clicked.connect(partial(self._toggle_queue, path, not queued))
        layout.addWidget(queue_btn)

        reindex_btn = QPushButton("Reindex")
        reindex_btn.clicked.connect(partial(self._trigger_reindex, path))
        layout.addWidget(reindex_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(partial(self._remove_entry, path))
        layout.addWidget(remove_btn)

        return container

    def _toggle_queue(self, path: str, queued: bool) -> None:
        entry = self.source_manager.queue_entry(path, queued)
        if entry:
            self._upsert_entry(entry)
            self._update_queue_indicator()

    def _trigger_reindex(self, path: str) -> None:
        self.source_manager.trigger_reindex_path(path)
        entry = self.source_manager.find_entry(path)
        if entry:
            self._upsert_entry(entry)
        self._update_queue_indicator()

    def _remove_entry(self, path: str) -> None:
        self.source_manager.remove_entry(path)
        self._set_status("Entry removed from recent list.")

    def _update_queue_indicator(self) -> None:
        queued = sum(1 for entry in self.source_manager.get_recent_entries() if entry.queued)
        total = len(self.source_manager.get_recent_entries())
        self.queue_count_label.setText(f"Queued: {queued} / {total}")
        self.process_button.setEnabled(queued > 0)
        self.clear_queue_button.setEnabled(queued > 0)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)
