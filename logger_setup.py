import logging
import json
import os
import sys
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    """Outputs log records as JSON."""

    # Computed once: the set of standard LogRecord attribute names
    _STANDARD_ATTRS = frozenset(logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys())

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage()
        }

        # Add exception info if present (guard against falsy (None, None, None) tuples)
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra attributes (anything passed in the 'extra' kwarg)
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and key not in ("message", "asctime"):
                try:
                    # just a quick test serialization
                    json.dumps(value)
                    log_data[key] = value
                except TypeError:
                    log_data[key] = str(value)
                    
        return json.dumps(log_data)

def setup_logging():
    """Configures centralized logging for the server process."""
    log_format = os.environ.get("LOG_FORMAT", "text").lower().strip()
    
    root_logger = logging.getLogger()
    
    # Remove existing root handlers to prevent duplication
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        # Default behavior mimicking logging.basicConfig() natively
        handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
        
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    # Intercept Uvicorn and FastAPI loggers and explicitly route them through
    # our centralized root logger configuration to prevent mixed format outputs.
    intercept_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]
    for logger_name in intercept_loggers:
        framework_logger = logging.getLogger(logger_name)
        # Clear existing handlers
        framework_logger.handlers = []
        # Let log records naturally bubble up to the root handlers
        framework_logger.propagate = True
