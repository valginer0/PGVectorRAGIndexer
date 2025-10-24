from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QFileDialog
from PySide6.QtGui import QGuiApplication

import os
import sys
import subprocess


@dataclass
class RecentEntry:
    path: str
    opened_at: datetime
    reindexed: bool = False
    last_error: Optional[str] = None


class SourceOpenManager(QObject):
    entry_added = Signal(object)
    entry_updated = Signal(object)
    entries_cleared = Signal()

    def __init__(self, api_client, parent=None, max_entries: int = 20):
        super().__init__(parent)
        self.api_client = api_client
        self.max_entries = max_entries
        self._recent_entries: List[RecentEntry] = []

    def get_recent_entries(self) -> List[RecentEntry]:
        return list(self._recent_entries)

    def clear_entries(self) -> None:
        self._recent_entries.clear()
        self.entries_cleared.emit()

    def open_path(self, path: str, mode: str = "default", prompt_reindex: bool = True) -> None:
        normalized = self._normalize_path(path, warn=mode not in {"copy_path"})
        if normalized is None:
            return

        try:
            if mode == "open_with":
                self._launch_open_with_dialog(normalized)
            elif mode == "show_in_folder":
                self._show_in_folder(normalized)
                prompt_reindex = False
            elif mode == "copy_path":
                self._copy_to_clipboard(normalized)
                prompt_reindex = False
            else:
                self._launch_default(normalized)
        except Exception as exc:
            QMessageBox.critical(self._parent_widget(), "Open Failed", f"Unable to open the file:\n{normalized}\n\nError: {exc}")
            return

        if mode in {"default", "open_with"}:
            entry = self._track_recent(str(normalized))
            if prompt_reindex:
                self._prompt_reindex(entry)

    def trigger_reindex_path(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        if normalized is None:
            return False
        entry = self._track_recent(str(normalized))
        return self._reindex_entry(entry)

    def _track_recent(self, path: str) -> RecentEntry:
        existing = next((e for e in self._recent_entries if e.path == path), None)
        if existing:
            existing.opened_at = datetime.utcnow()
            self.entry_updated.emit(existing)
            return existing

        entry = RecentEntry(path=path, opened_at=datetime.utcnow())
        self._recent_entries.insert(0, entry)
        if len(self._recent_entries) > self.max_entries:
            self._recent_entries.pop()
        self.entry_added.emit(entry)
        return entry

    def _prompt_reindex(self, entry: RecentEntry) -> None:
        reply = QMessageBox.question(
            self._parent_widget(),
            "Reindex Document?",
            f"Reindex the edited document now?\n\n{entry.path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._reindex_entry(entry)

    def _reindex_entry(self, entry: RecentEntry) -> bool:
        try:
            response = self.api_client.upload_document(
                Path(entry.path),
                custom_source_uri=entry.path,
                force_reindex=True
            )
            entry.reindexed = True
            entry.last_error = None
            self.entry_updated.emit(entry)
            QMessageBox.information(
                self._parent_widget(),
                "Reindex Started",
                f"Reindex request submitted for:\n{entry.path}"
            )
            return True
        except Exception as exc:
            entry.last_error = str(exc)
            self.entry_updated.emit(entry)
            QMessageBox.critical(
                self._parent_widget(),
                "Reindex Failed",
                f"Unable to reindex the document:\n{entry.path}\n\nError: {exc}"
            )
            return False

    def _normalize_path(self, path: str, warn: bool = True) -> Optional[Path]:
        if not path:
            if warn:
                QMessageBox.warning(
                    self._parent_widget(),
                    "No Path",
                    "No source path is available to open."
                )
            return None
        normalized = Path(path).expanduser()
        if not normalized.exists():
            if warn:
                QMessageBox.warning(
                    self._parent_widget(),
                    "File Not Found",
                    f"The file does not exist:\n{path}"
                )
            return None
        return normalized

    def _launch_default(self, path: Path) -> None:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _launch_open_with_dialog(self, path: Path) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(["rundll32", "shell32.dll,OpenAs_RunDLL", str(path)])
            return
        if sys.platform == "darwin":
            app, _ = QFileDialog.getOpenFileName(
                self._parent_widget(),
                "Choose Application",
                "/Applications",
                "Applications (*.app)"
            )
            if app:
                subprocess.Popen(["open", str(path), "-a", app])
            return
        app, _ = QFileDialog.getOpenFileName(
            self._parent_widget(),
            "Choose Application",
            "/usr/bin",
            "Executables (*)"
        )
        if app:
            subprocess.Popen([app, str(path)])

    def _show_in_folder(self, path: Path) -> None:
        folder = path.parent
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _copy_to_clipboard(self, path: Path) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(str(path))

    def _parent_widget(self):
        parent = self.parent()
        if hasattr(parent, "window"):
            return parent.window()
        return parent
