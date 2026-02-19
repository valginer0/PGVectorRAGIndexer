"""Shared UI helpers for the desktop application."""

from typing import Optional

from PySide6.QtWidgets import QComboBox


def populate_document_type_combo(
    combo: QComboBox,
    api_client,
    logger,
    *,
    blank_option: str = "",
    log_context: str = "document type loader"
) -> Optional[int]:
    """Populate a QComboBox with document types from the API.

    Args:
        combo: Combo box to populate.
        api_client: API client exposing ``get_metadata_values``.
        logger: Logger for success/error messages.
        blank_option: Label to insert as the first "all types" option.
        log_context: Additional context for log messages.

    Returns:
        The number of document types loaded on success, otherwise ``None``.
    """
    try:
        types = api_client.get_metadata_values("type")
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error(f"Failed to load document types for {log_context}: {exc}")
        return None

    current_text = combo.currentText()

    combo.blockSignals(True)
    combo.clear()
    combo.addItem(blank_option)

    for doc_type in sorted(types):
        if doc_type:
            combo.addItem(doc_type)

    if current_text:
        index = combo.findText(current_text)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(current_text)

    combo.blockSignals(False)

    logger.info(f"Loaded {len(types)} document types for {log_context}")
    return len(types)


import sys
import os
import subprocess
import webbrowser
from pathlib import Path
import logging

_logger = logging.getLogger(__name__)

def default_start_dir() -> str:
    """Return a sensible starting directory for file dialogs (WSL-aware).

    On WSL, returns the user's Windows home (e.g. /mnt/c/Users/john).
    Otherwise returns the user's home directory.
    """
    start = Path.home()
    wsl_win_home = Path("/mnt/c/Users")
    if wsl_win_home.exists():
        candidates = [
            d for d in wsl_win_home.iterdir()
            if d.is_dir() and not d.name.startswith(("Default", "Public", "All"))
        ]
        if len(candidates) == 1:
            start = candidates[0]
        else:
            start = wsl_win_home
    return str(start)


def pick_directory(parent, title: str = "Select Folder") -> str:
    """Show a properly-sized directory picker dialog. Returns path or empty string."""
    from PySide6.QtWidgets import QFileDialog

    dialog = QFileDialog(parent, title, default_start_dir())
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    dialog.resize(900, 560)
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0]
    return ""


def pick_save_file(parent, title: str, default_name: str, filter_str: str) -> str:
    """Show a properly-sized save-file dialog. Returns path or empty string."""
    from PySide6.QtWidgets import QFileDialog

    dialog = QFileDialog(parent, title, str(Path(default_start_dir()) / default_name))
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setNameFilter(filter_str)
    dialog.resize(900, 560)
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0]
    return ""


def pick_open_file(parent, title: str, filter_str: str) -> str:
    """Show a properly-sized open-file dialog. Returns path or empty string."""
    from PySide6.QtWidgets import QFileDialog

    dialog = QFileDialog(parent, title, default_start_dir())
    dialog.setFileMode(QFileDialog.ExistingFile)
    dialog.setNameFilter(filter_str)
    dialog.resize(900, 560)
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0]
    return ""


def pick_open_files(parent, title: str, filter_str: str) -> list:
    """Show a properly-sized open-files dialog. Returns list of paths."""
    from PySide6.QtWidgets import QFileDialog

    dialog = QFileDialog(parent, title, default_start_dir())
    dialog.setFileMode(QFileDialog.ExistingFiles)
    dialog.setNameFilter(filter_str)
    dialog.resize(900, 560)
    if dialog.exec():
        return dialog.selectedFiles()
    return []


def system_open(path: Path) -> None:
    """Open a file or directory using the system default application.
    
    Supports Windows, macOS, Linux, and WSL (opening in Windows).
    """
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        # Linux/Unix
        if _is_wsl():
            _open_in_wsl(path)
            return
            
        try:
            subprocess.Popen(["xdg-open", str(path)])
        except FileNotFoundError:
            # Fallback if xdg-open is missing
            _logger.warning("xdg-open not found, falling back to webbrowser")
            webbrowser.open(path.as_uri())

def _is_wsl() -> bool:
    """Check if running in WSL."""
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False

def _open_in_wsl(path: Path) -> None:
    """Open file using Windows default application via WSL."""
    try:
        # Convert Linux path to Windows path
        result = subprocess.run(
            ["wslpath", "-w", str(path)], 
            capture_output=True, 
            text=True, 
            check=True
        )
        windows_path = result.stdout.strip()
        
        # Open using cmd.exe /c start
        # We use Popen to not block
        subprocess.Popen(["cmd.exe", "/c", "start", "", windows_path])
        _logger.info(f"Opened in Windows via WSL: {windows_path}")
    except subprocess.CalledProcessError as e:
        _logger.error(f"Failed to convert path in WSL: {e}")
        raise e
    except Exception as e:
        _logger.error(f"Failed to open in WSL: {e}")
        raise e
