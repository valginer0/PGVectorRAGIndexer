import json
import logging
from typing import Any, Optional

from database import get_db_manager

logger = logging.getLogger(__name__)


class ServerSettingsStoreError(Exception):
    """Raised when reading or writing server_settings fails."""


_LICENSE_KEY_SETTING = "license_key"


def get_server_setting(key: str) -> Optional[Any]:
    """Read a JSON value from server_settings by key."""
    try:
        with get_db_manager().get_cursor() as cursor:
            cursor.execute("SELECT value FROM server_settings WHERE key = %s", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.debug("Failed to read server setting %s: %s", key, e)
        return None


def set_server_setting(key: str, value: Any) -> None:
    """Upsert a JSON-serializable value into server_settings."""
    try:
        payload = json.dumps(value)
        with get_db_manager().get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO server_settings (key, value)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, payload),
            )
    except Exception as e:
        logger.error("Failed to write server setting %s: %s", key, e)
        raise ServerSettingsStoreError(str(e))


def get_server_license_key() -> Optional[str]:
    """Return the server-stored license key, if any."""
    value = get_server_setting(_LICENSE_KEY_SETTING)
    if isinstance(value, dict):
        key = value.get("token") or value.get("license_key")
        return str(key).strip() if key else None
    if isinstance(value, str):
        return value.strip() or None
    return None


def set_server_license_key(license_key: str) -> None:
    """Persist the backend license key in server_settings."""
    set_server_setting(_LICENSE_KEY_SETTING, {"token": license_key.strip()})
