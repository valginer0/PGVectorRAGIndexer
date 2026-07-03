"""Tests for the desktop rotating log file and exception hooks.

Covers:
- Log file created under the given directory; records reach it
- Rotation configuration (maxBytes / backupCount / encoding)
- Idempotency: repeated setup never stacks duplicate handlers
- sys.excepthook and threading.excepthook write tracebacks to the file
- Log-directory creation failure falls back to console-only (returns None, no raise)
"""

import logging
import sys
import threading

import pytest

from desktop_app.utils import logging_setup
from desktop_app.utils.logging_setup import (
    setup_desktop_logging, LOG_FILE_NAME, MAX_BYTES, BACKUP_COUNT,
)
from logging.handlers import RotatingFileHandler


@pytest.fixture
def clean_logging_state():
    """Snapshot and restore global logging/hook state around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_excepthook = sys.excepthook
    saved_threading_hook = threading.excepthook
    saved_flag = logging_setup._hooks_installed
    yield
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)
    sys.excepthook = saved_excepthook
    threading.excepthook = saved_threading_hook
    logging_setup._hooks_installed = saved_flag


class TestLogFile:
    def test_creates_log_file_and_writes(self, tmp_path, clean_logging_state):
        log_path = setup_desktop_logging(log_dir=tmp_path / "logs")
        assert log_path == tmp_path / "logs" / LOG_FILE_NAME
        logging.getLogger("test.desktop").info("hello from the test")
        assert "hello from the test" in log_path.read_text(encoding="utf-8")

    def test_rotation_configuration(self, tmp_path, clean_logging_state):
        log_path = setup_desktop_logging(log_dir=tmp_path)
        handler = next(
            h for h in logging.getLogger().handlers
            if isinstance(h, RotatingFileHandler)
        )
        assert handler.maxBytes == MAX_BYTES
        assert handler.backupCount == BACKUP_COUNT
        assert str(log_path) == handler.baseFilename

    def test_idempotent_no_duplicate_handlers(self, tmp_path, clean_logging_state):
        setup_desktop_logging(log_dir=tmp_path)
        before = len(logging.getLogger().handlers)
        setup_desktop_logging(log_dir=tmp_path)
        setup_desktop_logging(log_dir=tmp_path)
        assert len(logging.getLogger().handlers) == before

    def test_log_dir_creation_failure_falls_back_to_console_only(
        self, tmp_path, clean_logging_state
    ):
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")

        result = setup_desktop_logging(log_dir=blocked / "logs")

        assert result is None  # no exception; startup must never block on logging


class TestExceptionHooks:
    def _read_log(self, tmp_path):
        return (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")

    def test_sys_excepthook_logs_traceback(self, tmp_path, clean_logging_state):
        # Neutralize the chained previous hook: pytest-qt fails any test whose
        # default excepthook fires. The chain itself is covered separately.
        sys.excepthook = lambda *a: None
        logging_setup._hooks_installed = False
        setup_desktop_logging(log_dir=tmp_path)
        try:
            raise PermissionError(5, "Access is denied", "/mnt/c/Users")
        except PermissionError:
            sys.excepthook(*sys.exc_info())
        log = self._read_log(tmp_path)
        assert "Unhandled exception" in log
        assert "PermissionError" in log
        assert "Access is denied" in log

    def test_keyboard_interrupt_not_logged(self, tmp_path, clean_logging_state):
        sys.excepthook = lambda *a: None
        logging_setup._hooks_installed = False
        setup_desktop_logging(log_dir=tmp_path)
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())
        assert "Unhandled exception" not in self._read_log(tmp_path)

    def test_threading_excepthook_logs(self, tmp_path, clean_logging_state):
        setup_desktop_logging(log_dir=tmp_path)

        def boom():
            raise ValueError("thread went boom")

        t = threading.Thread(target=boom, name="test-boom-thread")
        t.start()
        t.join()
        log = self._read_log(tmp_path)
        assert "test-boom-thread" in log
        assert "thread went boom" in log

    def test_hooks_chain_previous_hook(self, tmp_path, clean_logging_state):
        calls = []
        sys.excepthook = lambda *a: calls.append(a)
        logging_setup._hooks_installed = False
        setup_desktop_logging(log_dir=tmp_path)
        try:
            raise RuntimeError("chained")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert len(calls) == 1  # previous hook still ran
