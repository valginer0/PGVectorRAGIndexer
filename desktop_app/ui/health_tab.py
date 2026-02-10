"""
Health Dashboard tab (#4) — shows indexing run history and statistics.

Displays:
- Summary cards (total runs, success rate, files indexed, last run)
- Recent runs table with status, timing, and file counts
- Run detail view with error list
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
    QGridLayout,
)

from desktop_app.utils.api_client import APIClient

logger = logging.getLogger(__name__)


class _StatCard(QFrame):
    """A small card showing a label and a large value."""

    def __init__(self, title: str, value: str = "—", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #1e293b; border: 1px solid #334155; "
            "border-radius: 8px; padding: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self._title)

        self._value = QLabel(value)
        self._value.setStyleSheet("color: #f1f5f9; font-size: 22px; font-weight: bold;")
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class HealthTab(QWidget):
    """Indexing Health Dashboard tab."""

    def __init__(self, api_client: APIClient, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.api_client = api_client
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel("Indexing Health")
        title.setProperty("class", "header")
        title_row.addWidget(title)
        title_row.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        layout.addLayout(title_row)

        # Summary cards
        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)

        self._card_total = _StatCard("Total Runs")
        self._card_success = _StatCard("Success Rate")
        self._card_files = _StatCard("Files Indexed")
        self._card_last = _StatCard("Last Run")

        cards_layout.addWidget(self._card_total, 0, 0)
        cards_layout.addWidget(self._card_success, 0, 1)
        cards_layout.addWidget(self._card_files, 0, 2)
        cards_layout.addWidget(self._card_last, 0, 3)
        layout.addLayout(cards_layout)

        # Recent runs table
        runs_group = QGroupBox("Recent Runs")
        runs_layout = QVBoxLayout(runs_group)

        self._runs_table = QTableWidget()
        self._runs_table.setColumnCount(7)
        self._runs_table.setHorizontalHeaderLabels([
            "Status", "Trigger", "Started", "Duration",
            "Scanned", "Added", "Failed",
        ])
        self._runs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._runs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._runs_table.setAlternatingRowColors(True)
        self._runs_table.verticalHeader().setVisible(False)
        runs_layout.addWidget(self._runs_table)

        layout.addWidget(runs_group)

        # Error detail area (hidden by default)
        self._error_group = QGroupBox("Errors (select a run above)")
        error_layout = QVBoxLayout(self._error_group)
        self._error_label = QLabel("No errors.")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #9ca3af;")
        error_layout.addWidget(self._error_label)
        self._error_group.setVisible(False)
        layout.addWidget(self._error_group)

        # Wire row selection
        self._runs_table.currentCellChanged.connect(self._on_run_selected)

        # Store run data for detail lookup
        self._runs_data = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh(self):
        """Fetch latest data from the API and update the UI."""
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Loading...")
        try:
            self._load_summary()
            self._load_runs()
        except Exception as e:
            logger.warning("Health dashboard refresh failed: %s", e)
        finally:
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Refresh")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_summary(self):
        try:
            data = self.api_client.get_indexing_summary()
        except Exception:
            data = {}

        total = data.get("total_runs", 0)
        success = data.get("successful", 0)
        failed = data.get("failed", 0)
        files_added = data.get("total_files_added", 0)
        files_updated = data.get("total_files_updated", 0)
        last_run = data.get("last_run_at")

        self._card_total.set_value(str(total))

        if total > 0:
            rate = round(success / total * 100)
            self._card_success.set_value(f"{rate}%")
        else:
            self._card_success.set_value("—")

        self._card_files.set_value(str(files_added + files_updated))

        if last_run:
            self._card_last.set_value(self._format_relative_time(last_run))
        else:
            self._card_last.set_value("Never")

    def _load_runs(self):
        try:
            data = self.api_client.get_indexing_runs(limit=50)
            runs = data.get("runs", [])
        except Exception:
            runs = []

        self._runs_data = runs
        self._runs_table.setRowCount(len(runs))

        for row, run in enumerate(runs):
            status = run.get("status", "unknown")
            trigger = run.get("trigger", "")
            started = run.get("started_at", "")
            completed = run.get("completed_at")
            scanned = run.get("files_scanned", 0)
            added = run.get("files_added", 0)
            failed = run.get("files_failed", 0)

            # Status with color
            status_item = QTableWidgetItem(status.upper())
            status_item.setForeground(self._status_color(status))
            self._runs_table.setItem(row, 0, status_item)

            self._runs_table.setItem(row, 1, QTableWidgetItem(trigger))
            self._runs_table.setItem(row, 2, QTableWidgetItem(
                self._format_timestamp(started)
            ))
            self._runs_table.setItem(row, 3, QTableWidgetItem(
                self._format_duration(started, completed)
            ))
            self._runs_table.setItem(row, 4, QTableWidgetItem(str(scanned)))
            self._runs_table.setItem(row, 5, QTableWidgetItem(str(added)))

            failed_item = QTableWidgetItem(str(failed))
            if failed > 0:
                failed_item.setForeground(Qt.red)
            self._runs_table.setItem(row, 6, failed_item)

        self._error_group.setVisible(False)

    # ------------------------------------------------------------------
    # Detail
    # ------------------------------------------------------------------

    def _on_run_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int):
        if row < 0 or row >= len(self._runs_data):
            self._error_group.setVisible(False)
            return

        run = self._runs_data[row]
        errors = run.get("errors") or []
        if not errors:
            self._error_group.setTitle("Errors")
            self._error_label.setText("No errors for this run.")
            self._error_label.setStyleSheet("color: #9ca3af;")
            self._error_group.setVisible(True)
            return

        lines = []
        for err in errors[:20]:  # cap display
            src = err.get("source_uri", "unknown")
            msg = err.get("error", "unknown error")
            lines.append(f"<b>{src}</b>: {msg}")

        if len(errors) > 20:
            lines.append(f"<i>... and {len(errors) - 20} more</i>")

        self._error_group.setTitle(f"Errors ({len(errors)})")
        self._error_label.setText("<br>".join(lines))
        self._error_label.setStyleSheet("color: #fca5a5;")
        self._error_group.setVisible(True)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _status_color(status: str):
        from PySide6.QtGui import QColor
        colors = {
            "success": QColor("#4ade80"),
            "partial": QColor("#fbbf24"),
            "failed": QColor("#f87171"),
            "running": QColor("#60a5fa"),
        }
        return colors.get(status, QColor("#94a3b8"))

    @staticmethod
    def _format_timestamp(iso: str) -> str:
        if not iso:
            return "—"
        try:
            dt = datetime.fromisoformat(iso)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return iso[:16] if len(iso) >= 16 else iso

    @staticmethod
    def _format_duration(started: str, completed: Optional[str]) -> str:
        if not started or not completed:
            return "—"
        try:
            s = datetime.fromisoformat(started)
            c = datetime.fromisoformat(completed)
            delta = (c - s).total_seconds()
            if delta < 1:
                return "<1s"
            if delta < 60:
                return f"{int(delta)}s"
            if delta < 3600:
                return f"{int(delta // 60)}m {int(delta % 60)}s"
            return f"{int(delta // 3600)}h {int((delta % 3600) // 60)}m"
        except (ValueError, TypeError):
            return "—"

    @staticmethod
    def _format_relative_time(iso: str) -> str:
        if not iso:
            return "Never"
        try:
            dt = datetime.fromisoformat(iso)
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            delta = (now - dt).total_seconds()
            if delta < 60:
                return "Just now"
            if delta < 3600:
                return f"{int(delta // 60)}m ago"
            if delta < 86400:
                return f"{int(delta // 3600)}h ago"
            days = int(delta // 86400)
            return f"{days}d ago"
        except (ValueError, TypeError):
            return iso[:10]
