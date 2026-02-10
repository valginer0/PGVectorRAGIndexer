"""
Persistent application configuration for the desktop app.

Stores settings like backend mode (local/remote), backend URL, and API key
in a JSON file at the platform-appropriate config directory.
"""

import json
import logging
import os
import platform
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Config file location
_CONFIG_DIR_NAME = "PGVectorRAGIndexer"


def _get_config_dir() -> Path:
    """Get the platform-appropriate config directory."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / _CONFIG_DIR_NAME


def _get_config_path() -> Path:
    return _get_config_dir() / "settings.json"


def _load_all() -> dict:
    path = _get_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read config %s: %s", path, e)
        return {}


def _save_all(data: dict) -> None:
    path = _get_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to write config %s: %s", path, e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get(key: str, default: Any = None) -> Any:
    """Read a config value."""
    return _load_all().get(key, default)


def set(key: str, value: Any) -> None:
    """Write a config value (persisted immediately)."""
    data = _load_all()
    data[key] = value
    _save_all(data)


def delete(key: str) -> None:
    """Remove a config key."""
    data = _load_all()
    data.pop(key, None)
    _save_all(data)


# ---------------------------------------------------------------------------
# Convenience: backend mode
# ---------------------------------------------------------------------------

BACKEND_MODE_LOCAL = "local"
BACKEND_MODE_REMOTE = "remote"

DEFAULT_LOCAL_URL = "http://localhost:8000"


def get_backend_mode() -> str:
    """Return 'local' or 'remote'."""
    return get("backend_mode", BACKEND_MODE_LOCAL)


def set_backend_mode(mode: str) -> None:
    set("backend_mode", mode)


def get_backend_url() -> str:
    """Return the configured backend URL."""
    mode = get_backend_mode()
    if mode == BACKEND_MODE_LOCAL:
        return DEFAULT_LOCAL_URL
    return get("backend_url", DEFAULT_LOCAL_URL)


def set_backend_url(url: str) -> None:
    set("backend_url", url)


def get_api_key() -> Optional[str]:
    """Return the stored API key for remote connections (or None)."""
    return get("api_key")


def set_api_key(key: Optional[str]) -> None:
    if key:
        set("api_key", key)
    else:
        delete("api_key")


def is_remote_mode() -> bool:
    return get_backend_mode() == BACKEND_MODE_REMOTE
