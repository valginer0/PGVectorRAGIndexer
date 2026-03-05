"""
Phase E Verification Tests — Deep Observability & Startup Optimization

Automated equivalents of the manual QA checklist in docs/PHASE_E_VERIFICATION.md.
Covers: JSONFormatter edge cases, setup_logging idempotency, system metrics
types and monotonicity, exc_info handling, extra attribute passthrough.

Complements (does NOT duplicate) the existing tests in:
  - test_logger_setup.py (text/json format switching, uvicorn propagation)
  - test_system_health.py (health schema, psutil fallback, init path)
  - test_startup_hang_regression.py (offloaded DB, scheduler liveness)
"""

import json
import logging
import os
import time
import sys
import builtins
import pytest
from io import StringIO
from unittest.mock import patch

from logger_setup import JSONFormatter, setup_logging
from routers.system_api import _get_system_metrics


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_loggers():
    """Ensure root and framework loggers are clean before and after tests."""
    loggers_to_clean = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("fastapi"),
    ]
    original_handlers = {logger: logger.handlers[:] for logger in loggers_to_clean}
    original_levels = {logger: logger.level for logger in loggers_to_clean}
    yield
    for logger, handlers in original_handlers.items():
        logger.handlers = handlers
        logger.level = original_levels[logger]


# ---------------------------------------------------------------------------
# JSONFormatter Edge Cases
# ---------------------------------------------------------------------------

class TestJSONFormatterEdgeCases:
    """Verify JSONFormatter handles exc_info, extras, and non-serializable values."""

    def test_exc_info_included_in_json(self):
        """Exception tracebacks appear in the 'exception' field."""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="Something failed", args=(), exc_info=sys.exc_info()
            )
        output = json.loads(formatter.format(record))
        assert "exception" in output
        assert "ValueError: test error" in output["exception"]

    def test_falsy_exc_info_excluded(self):
        """Falsy exc_info (None, None, None) does NOT produce 'exception' key."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="OK", args=(), exc_info=(None, None, None)
        )
        output = json.loads(formatter.format(record))
        assert "exception" not in output

    def test_no_exc_info_excluded(self):
        """No exc_info at all does NOT produce 'exception' key."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="OK", args=(), exc_info=None
        )
        output = json.loads(formatter.format(record))
        assert "exception" not in output

    def test_extra_attributes_serialized(self):
        """Extra kwargs are included in JSON output."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test.extras")
        logger.handlers = [logging.StreamHandler(StringIO())]
        logger.handlers[0].setFormatter(formatter)

        record = logger.makeRecord(
            "test.extras", logging.INFO, "", 0, "msg", (), None
        )
        record.request_id = "abc-123"
        record.status_code = 200

        output = json.loads(formatter.format(record))
        assert output["request_id"] == "abc-123"
        assert output["status_code"] == 200

    def test_non_serializable_extra_stringified(self):
        """Non-JSON-serializable extras are converted to str()."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None
        )
        record.custom_obj = object()  # not JSON serializable

        output = json.loads(formatter.format(record))
        assert "custom_obj" in output
        assert output["custom_obj"].startswith("<object object at")

    def test_timestamp_is_iso8601(self):
        """Timestamp field is ISO 8601 format with timezone."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None
        )
        output = json.loads(formatter.format(record))
        ts = output["timestamp"]
        # ISO 8601 with +00:00 suffix
        assert "T" in ts
        assert ts.endswith("+00:00")

    def test_standard_attrs_not_leaked(self):
        """Standard LogRecord attributes (pathname, lineno, etc.) are not in output."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="/some/path.py", lineno=42,
            msg="msg", args=(), exc_info=None
        )
        output = json.loads(formatter.format(record))
        # These standard attrs should NOT appear in the JSON
        assert "pathname" not in output
        assert "lineno" not in output
        assert "funcName" not in output
        assert "processName" not in output


# ---------------------------------------------------------------------------
# setup_logging Idempotency
# ---------------------------------------------------------------------------

class TestSetupLoggingIdempotency:
    """Verify calling setup_logging multiple times doesn't duplicate handlers."""

    def test_no_duplicate_handlers(self, clean_loggers):
        """Calling setup_logging twice leaves exactly one handler on root."""
        with patch.dict(os.environ, {"LOG_FORMAT": "text"}):
            with patch("sys.stdout", new_callable=StringIO):
                setup_logging()
                setup_logging()
                root = logging.getLogger()
                assert len(root.handlers) == 1

    def test_no_duplicate_json_handlers(self, clean_loggers):
        """Calling setup_logging twice in JSON mode leaves exactly one handler."""
        with patch.dict(os.environ, {"LOG_FORMAT": "json"}):
            with patch("sys.stdout", new_callable=StringIO):
                setup_logging()
                setup_logging()
                root = logging.getLogger()
                assert len(root.handlers) == 1
                assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_no_duplicate_log_output(self, clean_loggers):
        """A single log event produces exactly one line (not duplicated)."""
        with patch.dict(os.environ, {"LOG_FORMAT": "json"}):
            buf = StringIO()
            with patch("sys.stdout", buf):
                setup_logging()
                setup_logging()  # second call
                logger = logging.getLogger("test.dedup")
                logger.info("unique_message_12345")

            lines = [l for l in buf.getvalue().split("\n") if "unique_message_12345" in l]
            assert len(lines) == 1

    def test_framework_loggers_have_no_handlers(self, clean_loggers):
        """After setup_logging, uvicorn/fastapi loggers have zero handlers."""
        with patch.dict(os.environ, {"LOG_FORMAT": "json"}):
            with patch("sys.stdout", new_callable=StringIO):
                setup_logging()
                for name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
                    logger = logging.getLogger(name)
                    assert len(logger.handlers) == 0, f"{name} should have 0 handlers"
                    assert logger.propagate is True, f"{name} should propagate"


# ---------------------------------------------------------------------------
# System Metrics Types & Monotonicity
# ---------------------------------------------------------------------------

class TestSystemMetrics:
    """Verify _get_system_metrics returns correct types and monotonic uptime."""

    def test_metrics_keys_present(self):
        """All three required keys are present."""
        metrics = _get_system_metrics()
        assert "uptime_seconds" in metrics
        assert "cpu_load_1m" in metrics
        assert "memory_rss_bytes" in metrics

    def test_uptime_is_nonnegative_number(self):
        """uptime_seconds is a non-negative number."""
        metrics = _get_system_metrics()
        assert isinstance(metrics["uptime_seconds"], (int, float))
        assert metrics["uptime_seconds"] >= 0

    def test_uptime_increases(self):
        """uptime_seconds increases between calls."""
        m1 = _get_system_metrics()
        time.sleep(0.05)
        m2 = _get_system_metrics()
        assert m2["uptime_seconds"] > m1["uptime_seconds"]

    def test_cpu_load_type(self):
        """cpu_load_1m is None or a number."""
        metrics = _get_system_metrics()
        val = metrics["cpu_load_1m"]
        assert val is None or isinstance(val, (int, float))

    def test_memory_rss_type(self):
        """memory_rss_bytes is None or a number."""
        metrics = _get_system_metrics()
        val = metrics["memory_rss_bytes"]
        assert val is None or isinstance(val, (int, float))

    def test_psutil_fallback_still_returns_dict(self):
        """Without psutil, _get_system_metrics still returns a valid dict."""
        saved = sys.modules.pop("psutil", None)
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("mocked: psutil not installed")
            return real_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, "__import__", side_effect=mock_import):
                metrics = _get_system_metrics()
        finally:
            if saved is not None:
                sys.modules["psutil"] = saved

        assert "uptime_seconds" in metrics
        assert "cpu_load_1m" in metrics
        assert "memory_rss_bytes" in metrics
        assert isinstance(metrics["uptime_seconds"], (int, float))
