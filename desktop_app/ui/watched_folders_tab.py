"""
Watched Folders tab (#6) — manage folders for scheduled automatic indexing.

Displays:
- List of watched folders with path, schedule, status, and last scanned time
- Add/Remove/Enable/Disable controls
- Per-folder schedule settings (cron expression presets)
- "Scan Now" button for immediate scanning
- Scheduler toggle (start/stop in-app scheduler)
"""

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QGroupBox,
    QFrame,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QAbstractItemView,
)

from desktop_app.utils.api_client import APIClient

logger = logging.getLogger(__name__)

# Schedule presets: display name → cron expression
_SCHEDULE_PRESETS = [
    ("Every hour", "0 * * * *"),
    ("Every 3 hours", "0 */3 * * *"),
    ("Every 6 hours", "0 */6 * * *"),
    ("Every 12 hours", "0 */12 * * *"),
    ("Daily (midnight)", "0 0 * * *"),
]


class WatchedFoldersTab(QWidget):
    """Tab for managing watched folders and the in-app scheduler."""

    def __init__(self, api_client: APIClient, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._api_client = api_client
        self._scheduler = None  # Set via set_scheduler()
        self._folders = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler):
        """Attach the FolderScheduler instance for start/stop control."""
        self._scheduler = scheduler
        if scheduler:
            scheduler.scan_started.connect(self._on_scan_started)
            scheduler.scan_completed.connect(self._on_scan_completed)
            scheduler.scan_failed.connect(self._on_scan_failed)
        self._update_scheduler_button()

    def load_folders(self):
        """Fetch watched folders from the API and refresh the table."""
        try:
            data = self._api_client.list_watched_folders()
            self._folders = data.get("folders", [])
        except Exception as e:
            logger.warning("Failed to load watched folders: %s", e)
            self._folders = []
        self._populate_table()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Watched Folders")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self._scheduler_btn = QPushButton("Start Scheduler")
        self._scheduler_btn.setMinimumWidth(160)
        self._scheduler_btn.clicked.connect(self._toggle_scheduler)
        header.addWidget(self._scheduler_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setMinimumWidth(100)
        self._refresh_btn.clicked.connect(self.load_folders)
        header.addWidget(self._refresh_btn)

        layout.addLayout(header)

        # Toolbar
        toolbar = QHBoxLayout()

        self._add_btn = QPushButton("+ Add Folder")
        self._add_btn.clicked.connect(self._add_folder)
        toolbar.addWidget(self._add_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._remove_folder)
        toolbar.addWidget(self._remove_btn)

        self._enable_btn = QPushButton("Enable")
        self._enable_btn.setEnabled(False)
        self._enable_btn.clicked.connect(lambda: self._set_enabled(True))
        toolbar.addWidget(self._enable_btn)

        self._disable_btn = QPushButton("Disable")
        self._disable_btn.setEnabled(False)
        self._disable_btn.clicked.connect(lambda: self._set_enabled(False))
        toolbar.addWidget(self._disable_btn)

        toolbar.addStretch()

        sched_label = QLabel("Schedule:")
        toolbar.addWidget(sched_label)

        self._schedule_combo = QComboBox()
        for label, _cron in _SCHEDULE_PRESETS:
            self._schedule_combo.addItem(label)
        self._schedule_combo.setFixedWidth(160)
        self._schedule_combo.currentIndexChanged.connect(self._change_schedule)
        toolbar.addWidget(self._schedule_combo)

        self._scan_now_btn = QPushButton("Scan Now")
        self._scan_now_btn.setEnabled(False)
        self._scan_now_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            "padding: 4px 12px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:disabled { background-color: #94a3b8; }"
        )
        self._scan_now_btn.clicked.connect(self._scan_now)
        toolbar.addWidget(self._scan_now_btn)

        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Folder Path", "Schedule", "Enabled", "Last Scanned", "Last Status", "Client"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        # Status bar
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self):
        self._table.setRowCount(len(self._folders))
        for row, folder in enumerate(self._folders):
            # Path
            self._table.setItem(row, 0, QTableWidgetItem(folder.get("folder_path", "")))

            # Schedule (human-readable)
            cron = folder.get("schedule_cron", "")
            display = cron
            for label, expr in _SCHEDULE_PRESETS:
                if expr == cron:
                    display = label
                    break
            self._table.setItem(row, 1, QTableWidgetItem(display))

            # Enabled
            enabled = folder.get("enabled", False)
            item = QTableWidgetItem("Yes" if enabled else "No")
            item.setForeground(
                Qt.darkGreen if enabled else Qt.darkRed
            )
            self._table.setItem(row, 2, item)

            # Last scanned
            last = folder.get("last_scanned_at")
            if last:
                try:
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    display_time = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    display_time = last[:16] if len(last) > 16 else last
            else:
                display_time = "Never"
            self._table.setItem(row, 3, QTableWidgetItem(display_time))

            # Last status (from last_run_id — we just show if it exists)
            run_id = folder.get("last_run_id")
            status_text = "—" if not run_id else "Completed"
            self._table.setItem(row, 4, QTableWidgetItem(status_text))

            # Client
            client_id = folder.get("client_id") or "—"
            if client_id != "—" and len(client_id) > 8:
                client_id = client_id[:8] + "…"
            self._table.setItem(row, 5, QTableWidgetItem(client_id))

        count = len(self._folders)
        enabled_count = sum(1 for f in self._folders if f.get("enabled"))
        self._status_label.setText(
            f"{count} folder{'s' if count != 1 else ''} "
            f"({enabled_count} enabled)"
        )
        self._on_selection_changed()

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _selected_folder(self):
        """Return the currently selected folder dict, or None."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._folders):
            return self._folders[idx]
        return None

    def _on_selection_changed(self):
        has_sel = self._selected_folder() is not None
        self._remove_btn.setEnabled(has_sel)
        self._enable_btn.setEnabled(has_sel)
        self._disable_btn.setEnabled(has_sel)
        self._scan_now_btn.setEnabled(has_sel)

        # Sync schedule combo to selected folder
        folder = self._selected_folder()
        if folder:
            cron = folder.get("schedule_cron", "")
            for i, (_label, expr) in enumerate(_SCHEDULE_PRESETS):
                if expr == cron:
                    self._schedule_combo.blockSignals(True)
                    self._schedule_combo.setCurrentIndex(i)
                    self._schedule_combo.blockSignals(False)
                    break

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add_folder(self):
        from .shared import pick_directory
        folder_path = pick_directory(self, "Select Folder to Watch")
        if not folder_path:
            return

        # Get client_id from app_config
        client_id = None
        try:
            from desktop_app.utils.app_config import get
            client_id = get("client_id")
        except Exception:
            pass

        try:
            self._api_client.add_watched_folder(
                folder_path=folder_path,
                client_id=client_id,
            )
            self.load_folders()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add folder:\n{e}")

    def _remove_folder(self):
        folder = self._selected_folder()
        if not folder:
            return
        reply = QMessageBox.question(
            self,
            "Remove Folder",
            f"Remove watched folder?\n\n{folder.get('folder_path', '')}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._api_client.remove_watched_folder(folder["id"])
            self.load_folders()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to remove folder:\n{e}")

    def _set_enabled(self, enabled: bool):
        folder = self._selected_folder()
        if not folder:
            return
        try:
            self._api_client.update_watched_folder(folder["id"], enabled=enabled)
            self.load_folders()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to update folder:\n{e}")

    def _change_schedule(self, index: int):
        folder = self._selected_folder()
        if not folder:
            return
        if 0 <= index < len(_SCHEDULE_PRESETS):
            _label, cron = _SCHEDULE_PRESETS[index]
            try:
                self._api_client.update_watched_folder(
                    folder["id"], schedule_cron=cron
                )
                self.load_folders()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to update schedule:\n{e}")

    def _scan_now(self):
        folder = self._selected_folder()
        if not folder:
            return

        client_id = None
        try:
            from desktop_app.utils.app_config import get
            client_id = get("client_id")
        except Exception:
            pass

        self._scan_now_btn.setEnabled(False)
        self._scan_now_btn.setText("Scanning…")
        try:
            result = self._api_client.scan_watched_folder(
                folder["id"], client_id=client_id
            )
            status = result.get("status", "unknown")
            scanned = result.get("files_scanned", 0)
            added = result.get("files_added", 0)
            QMessageBox.information(
                self,
                "Scan Complete",
                f"Status: {status}\n"
                f"Files scanned: {scanned}\n"
                f"Files added: {added}",
            )
            self.load_folders()
        except Exception as e:
            QMessageBox.warning(self, "Scan Failed", f"Error:\n{e}")
        finally:
            self._scan_now_btn.setText("Scan Now")
            self._on_selection_changed()

    # ------------------------------------------------------------------
    # Scheduler control
    # ------------------------------------------------------------------

    def _toggle_scheduler(self):
        if not self._scheduler:
            QMessageBox.information(
                self, "Scheduler", "Scheduler not available."
            )
            return
        if self._scheduler.is_running:
            self._scheduler.stop()
        else:
            self._scheduler.start()
        self._update_scheduler_button()

    def _update_scheduler_button(self):
        if self._scheduler and self._scheduler.is_running:
            self._scheduler_btn.setText("Stop Scheduler")
            self._scheduler_btn.setStyleSheet(
                "QPushButton { background-color: #dc2626; color: white; "
                "padding: 4px 12px; border-radius: 4px; font-weight: 600; }"
                "QPushButton:hover { background-color: #b91c1c; }"
            )
        else:
            self._scheduler_btn.setText("Start Scheduler")
            self._scheduler_btn.setStyleSheet(
                "QPushButton { background-color: #16a34a; color: white; "
                "padding: 4px 12px; border-radius: 4px; font-weight: 600; }"
                "QPushButton:hover { background-color: #15803d; }"
            )

    # ------------------------------------------------------------------
    # Scheduler signal handlers
    # ------------------------------------------------------------------

    def _on_scan_started(self, folder_id: str, folder_path: str):
        self._status_label.setText(f"Scanning: {folder_path}…")

    def _on_scan_completed(self, folder_id: str, result: dict):
        status = result.get("status", "unknown")
        self._status_label.setText(f"Scan complete: {status}")
        self.load_folders()

    def _on_scan_failed(self, folder_id: str, error: str):
        self._status_label.setText(f"Scan failed: {error}")
