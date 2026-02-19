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
import webbrowser

import logging
from .shared import system_open

logger = logging.getLogger(__name__)


@dataclass
class RecentEntry:
    path: str
    opened_at: datetime
    reindexed: bool = False
    queued: bool = False
    last_error: Optional[str] = None


class SourceOpenManager(QObject):
    entry_added = Signal(object)
    entry_updated = Signal(object)
    entry_removed = Signal(object)
    entries_cleared = Signal()

    def __init__(self, api_client, parent=None, max_entries: int = 20, project_root: Optional[Path] = None):
        super().__init__(parent)
        self.api_client = api_client
        self.max_entries = max_entries
        self.project_root = project_root
        self._recent_entries: List[RecentEntry] = []

    # ... (existing methods) ...

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
            # Try to resolve path mismatch (e.g. Windows path on Linux)
            resolved = self._resolve_path_mismatch(path)
            if resolved:
                return resolved
                
            if warn:
                QMessageBox.warning(
                    self._parent_widget(),
                    "File Not Found",
                    f"The file does not exist:\n{path}\n\n"
                    f"I also tried searching for '{normalized.name}' in the documents folder but couldn't find it."
                )
            return None
            
        return normalized

    def _resolve_path_mismatch(self, original_path: str) -> Optional[Path]:
        """Attempt to resolve a path that doesn't exist locally.

        Handles:
        1. Windows paths on WSL  (C:\\Users\\... → /mnt/c/Users/...)
        2. Fallback search by filename in project documents directory
        """
        logger.info(f"Attempting to resolve path mismatch for: {original_path}")

        # 1. Windows path on WSL/Linux → /mnt/<drive>/...
        if sys.platform != "win32" and len(original_path) >= 3 and original_path[1:3] in (":\\", ":/"):
            drive = original_path[0].lower()
            rest = original_path[3:].replace("\\", "/")
            wsl_path = Path(f"/mnt/{drive}/{rest}")
            if wsl_path.exists():
                logger.info(f"Resolved Windows path to WSL: {wsl_path}")
                return wsl_path

        # 2. Fallback: search by filename in project documents dir
        if not self.project_root:
            logger.warning("Project root not set in SourceOpenManager")
            return None

        filename = Path(original_path).name
        documents_dir = self.project_root / "documents"

        if not documents_dir.exists():
            logger.warning(f"Documents directory not found: {documents_dir}")
            return None

        try:
            found = list(documents_dir.rglob(filename))
            if found:
                logger.info(f"Found {len(found)} candidate(s): {found}")
                if len(found) > 1:
                    parent_name = Path(original_path).parent.name
                    for f in found:
                        if f.parent.name == parent_name:
                            logger.info(f"Matched parent folder '{parent_name}': {f}")
                            return f
                logger.info(f"Returning first match: {found[0]}")
                return found[0]
            else:
                logger.warning(f"No file named '{filename}' found in {documents_dir}")
        except Exception as e:
            logger.error(f"Error during path resolution: {e}")

        return None

    def get_recent_entries(self) -> List[RecentEntry]:
        return list(self._recent_entries)

    def clear_entries(self) -> None:
        self._recent_entries.clear()
        self.entries_cleared.emit()

    def find_entry(self, path: str) -> Optional[RecentEntry]:
        normalized = Path(path).expanduser()
        return next((e for e in self._recent_entries if e.path == str(normalized)), None)

    def open_path(self, path: str, mode: str = "default", auto_queue: bool = True) -> None:
        normalized = self._normalize_path(path, warn=mode not in {"copy_path"})
        if normalized is None:
            return

        try:
            if mode == "open_with":
                self._launch_open_with_dialog(normalized)
            elif mode == "show_in_folder":
                self._show_in_folder(normalized)
                auto_queue = False
            elif mode == "copy_path":
                self._copy_to_clipboard(normalized)
                auto_queue = False
            else:
                self._launch_default(normalized)
        except Exception as exc:
            QMessageBox.critical(self._parent_widget(), "Open Failed", f"Unable to open the file:\n{normalized}\n\nError: {exc}")
            return

        if mode in {"default", "open_with"}:
            entry = self._track_recent(str(normalized))
            if auto_queue:
                self._set_entry_queued(entry, True)

    def trigger_reindex_path(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        if normalized is None:
            return False
        entry = self._track_recent(str(normalized))
        return self._reindex_entry(entry)

    def queue_entry(self, path: str, queued: bool) -> Optional[RecentEntry]:
        normalized = self._normalize_path(path, warn=False)
        if normalized is None:
            return None
        entry = self._track_recent(str(normalized))
        self._set_entry_queued(entry, queued)
        return entry

    def remove_entry(self, path: str) -> bool:
        normalized = Path(path).expanduser()
        entry = next((e for e in self._recent_entries if e.path == str(normalized)), None)
        if entry is None:
            return False
        self._recent_entries.remove(entry)
        self.entry_removed.emit(entry)
        return True

    def clear_queue(self) -> bool:
        changed = False
        for entry in self._recent_entries:
            if entry.queued:
                entry.queued = False
                self.entry_updated.emit(entry)
                changed = True
        return changed

    def process_queue(self) -> tuple[int, int]:
        queued_entries = [entry for entry in self._recent_entries if entry.queued]
        if not queued_entries:
            return 0, 0

        success = 0
        failures = 0
        for entry in list(queued_entries):
            if self._reindex_entry(entry):
                success += 1
            else:
                failures += 1

        return success, failures

    def _track_recent(self, path: str) -> RecentEntry:
        existing = next((e for e in self._recent_entries if e.path == path), None)
        if existing:
            existing.opened_at = datetime.utcnow()
            existing.reindexed = False if existing.queued else existing.reindexed
            self._recent_entries.remove(existing)
            self._recent_entries.insert(0, existing)
            self.entry_updated.emit(existing)
            return existing

        entry = RecentEntry(path=path, opened_at=datetime.utcnow())
        self._recent_entries.insert(0, entry)
        if len(self._recent_entries) > self.max_entries:
            self._recent_entries.pop()
        self.entry_added.emit(entry)
        return entry

    def _reindex_entry(self, entry: RecentEntry) -> bool:
        try:
            # Try to preserve existing document type
            document_type = None
            try:
                # Search for the document to get its metadata
                # We use search because list_documents doesn't support filtering by exact URI easily
                # and we want to be robust.
                results = self.api_client.search(
                    query="", 
                    top_k=1, 
                    filters={"source_uri": entry.path}
                )
                if results:
                    metadata = results[0].get("metadata", {})
                    document_type = metadata.get("type")
                    if document_type:
                        logger.info(f"Preserving document type '{document_type}' for {entry.path}")
            except Exception as e:
                logger.warning(f"Failed to fetch existing metadata for {entry.path}: {e}")

            response = self.api_client.upload_document(
                Path(entry.path),
                custom_source_uri=entry.path,
                force_reindex=True,
                document_type=document_type
            )
            entry.reindexed = True
            entry.queued = False
            entry.last_error = None
            self.entry_updated.emit(entry)
            return True
        except Exception as exc:
            entry.last_error = str(exc)
            entry.queued = True
            self.entry_updated.emit(entry)
            return False

    def _set_entry_queued(self, entry: RecentEntry, queued: bool) -> None:
        if entry.queued == queued:
            return
        entry.queued = queued
        if queued:
            entry.reindexed = False
        self.entry_updated.emit(entry)



    def _launch_default(self, path: Path) -> None:
        try:
            system_open(path)
        except Exception as e:
            logger.error(f"Failed to open file {path}: {e}")
            raise e

    def _launch_open_with_dialog(self, path: Path) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(["rundll32", "shell32.dll,OpenAs_RunDLL", str(path)])
            return
            
        # For macOS and Linux, we use QFileDialog to pick an app
        if sys.platform == "darwin":
            base_dir = "/Applications"
            filter_str = "Applications (*.app)"
        else:
            base_dir = "/usr/bin"
            filter_str = "Executables (*)"
            
        app, _ = QFileDialog.getOpenFileName(
            self._parent_widget(),
            "Choose Application",
            base_dir,
            filter_str
        )
        
        if not app:
            return
            
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path), "-a", app])
        else:
            subprocess.Popen([app, str(path)])

    def _show_in_folder(self, path: Path) -> None:
        system_open(path.parent)

    def _copy_to_clipboard(self, path: Path) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(str(path))

    def _parent_widget(self):
        parent = self.parent()
        if hasattr(parent, "window"):
            return parent.window()
        return parent
