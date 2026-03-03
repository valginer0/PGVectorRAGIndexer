import logging
import json
import os
import pytest
from unittest.mock import patch
from io import StringIO
from logger_setup import setup_logging

@pytest.fixture
def clean_loggers():
    """Ensure root and uvicorn loggers are clean before and after tests."""
    loggers_to_clean = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.access"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("fastapi")
    ]
    
    # Save original handlers
    original_handlers = {logger: logger.handlers[:] for logger in loggers_to_clean}
    
    yield
    
    # Restore
    for logger, handlers in original_handlers.items():
        logger.handlers = handlers


def test_default_plaintext_assertion(clean_loggers):
    """Verify standard plaintext logging is the default format."""
    with patch.dict(os.environ, {}, clear=True), patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        setup_logging()
    
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.disabled = False
        uvicorn_access.setLevel(logging.INFO)
        assert uvicorn_access.propagate is True
        assert len(uvicorn_access.handlers) == 0
        
        uvicorn_access.info("Test access log")
        
        output = mock_stdout.getvalue()
        assert "INFO:" in output
        assert "Test access log" in output
        assert "{" not in output # Not JSON


def test_json_formatting_assertion(clean_loggers):
    """Verify JSON logging explicitly targets uvicorn access/error loggers."""
    with patch.dict(os.environ, {"LOG_FORMAT": "json"}), patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        setup_logging()
        
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_error = logging.getLogger("uvicorn.error")
        uvicorn_access.disabled = False
        uvicorn_error.disabled = False
        uvicorn_access.setLevel(logging.INFO)
        uvicorn_error.setLevel(logging.ERROR)
        
        uvicorn_access.info("Request completed", extra={"status_code": 200, "method": "GET"})
        uvicorn_error.error("Request failed")
        
        output = mock_stdout.getvalue()
        lines = [line for line in output.split("\n") if line.strip()]
        
        assert len(lines) == 2
        
        access_log = json.loads(lines[0])
        assert access_log["name"] == "uvicorn.access"
        assert access_log["level"] == "INFO"
        assert access_log["message"] == "Request completed"
        assert access_log["status_code"] == 200
        assert access_log["method"] == "GET"
        assert "timestamp" in access_log
        
        error_log = json.loads(lines[1])
        assert error_log["name"] == "uvicorn.error"
        assert error_log["level"] == "ERROR"
        assert error_log["message"] == "Request failed"
