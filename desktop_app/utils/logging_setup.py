"""Rotating file logging + crash visibility for the desktop app.

Windowed (no-console) builds swallow stderr, which made real failures
invisible (e.g. the Upload-tab picker crash fixed in 53ef83a). This module
adds a rotating log file under the app data directory and hooks unhandled
exceptions — including tracebacks raised inside Qt slots, which PySide6
routes through sys.excepthook — so every silent failure leaves evidence.
"""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_FILE_NAME = "desktop.log"
MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file
BACKUP_COUNT = 3             # desktop.log + .1/.2/.3 ≈ 8 MB worst case

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

_hooks_installed = False


def default_log_dir() -> Path:
    """logs/ next to settings.json (e.g. %APPDATA%/PGVectorRAGIndexer/logs)."""
    from .app_config import _get_config_dir
    return _get_config_dir() / "logs"


def setup_desktop_logging(log_dir: Optional[Path] = None,
                          level: int = logging.INFO) -> Optional[Path]:
    """Configure console + rotating-file logging and exception hooks.

    Idempotent: repeated calls never stack duplicate handlers or hooks.
    Returns the log file path, or None when the file handler could not be
    created (console-only fallback — never blocks app startup).
    """
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    if not any(type(h) is logging.StreamHandler for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    log_path: Optional[Path] = None
    try:
        directory = Path(log_dir) if log_dir is not None else default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / LOG_FILE_NAME
        already = any(
            isinstance(h, RotatingFileHandler)
            and Path(h.baseFilename) == log_path
            for h in root.handlers
        )
        if not already:
            file_handler = RotatingFileHandler(
                log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
    except OSError as e:
        root.warning("Could not create log file (console-only): %s", e)
        log_path = None

    _install_exception_hooks()
    return log_path


def _install_exception_hooks() -> None:
    """Log unhandled exceptions from the main thread, Qt slots, and threads.

    PySide6 delivers uncaught slot exceptions through sys.excepthook, so this
    also captures the 'button silently does nothing' failure class. The
    previous hooks are chained, keeping default stderr printing for console
    runs.
    """
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    crash_logger = logging.getLogger("desktop.unhandled")

    previous_excepthook = sys.excepthook

    def _logging_excepthook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            crash_logger.critical(
                "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
            )
        previous_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _logging_excepthook

    previous_threading_hook = threading.excepthook

    def _logging_threading_hook(args):
        if args.exc_type is not SystemExit:
            name = args.thread.name if args.thread else "?"
            crash_logger.critical(
                "Unhandled exception in thread %s", name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        previous_threading_hook(args)

    threading.excepthook = _logging_threading_hook
