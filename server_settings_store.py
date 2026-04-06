import json
import logging
from typing import Any, Optional

from database import get_db_manager

logger = logging.getLogger(__name__)


class ServerSettingsStoreError(Exception):
    """Raised when reading or writing server_settings fails."""


_LICENSE_KEY_SETTING = "license_key"
_LICENSE_KEYS_SETTING = "license_keys"


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
    """Return the server-stored license key, if any.

    Legacy single-key helper — kept for backward compatibility.
    Use ``get_server_license_keys()`` to retrieve all stacked keys.
    """
    keys = get_server_license_keys()
    return keys[0] if keys else None


def set_server_license_key(license_key: str) -> None:
    """Persist the backend license key in server_settings.

    Legacy single-key helper — replaces all existing keys with this one.
    Use ``add_server_license_key()`` to stack without replacing.
    """
    set_server_setting(_LICENSE_KEYS_SETTING, [license_key.strip()])


# ---------------------------------------------------------------------------
# Multi-key (stacking) helpers
# ---------------------------------------------------------------------------


def get_server_license_keys() -> list:
    """Return all server-stored license JWT strings as a list.

    Migrates the legacy single ``license_key`` entry on first read so
    existing installations keep working without data loss.
    """
    # Try the new array setting first
    value = get_server_setting(_LICENSE_KEYS_SETTING)
    if isinstance(value, list) and value:
        return [str(k).strip() for k in value if k]

    # Migration: read the old single-key entry and promote it
    old_value = get_server_setting(_LICENSE_KEY_SETTING)
    old_key: Optional[str] = None
    if isinstance(old_value, dict):
        raw = old_value.get("token") or old_value.get("license_key")
        old_key = str(raw).strip() if raw else None
    elif isinstance(old_value, str):
        old_key = old_value.strip() or None

    if old_key:
        # Persist under the new key and return
        try:
            set_server_setting(_LICENSE_KEYS_SETTING, [old_key])
        except Exception:
            pass
        return [old_key]

    return []


def add_server_license_key(license_key: str) -> None:
    """Append a license key to the stack.

    Deduplicates by JWT ``kid`` claim so the same physical key cannot be
    added twice.  Raises ``ServerSettingsStoreError`` on DB failure.
    """
    license_key = license_key.strip()
    if not license_key:
        raise ValueError("license_key must not be empty")

    # Extract kid for dedup (best-effort — no verification here)
    new_kid: Optional[str] = None
    try:
        import jwt as _jwt
        header = _jwt.get_unverified_header(license_key)
        new_kid = header.get("kid") or _jwt.decode(
            license_key,
            options={"verify_signature": False},
        ).get("kid")
    except Exception:
        pass

    existing = get_server_license_keys()

    if new_kid:
        for existing_key in existing:
            try:
                import jwt as _jwt
                existing_header = _jwt.get_unverified_header(existing_key)
                existing_kid = existing_header.get("kid") or _jwt.decode(
                    existing_key,
                    options={"verify_signature": False},
                ).get("kid")
                if existing_kid and existing_kid == new_kid:
                    logger.info("License key %s already present — skipping duplicate", new_kid)
                    return
            except Exception:
                continue

    existing.append(license_key)
    set_server_setting(_LICENSE_KEYS_SETTING, existing)


def remove_server_license_key(kid: str) -> bool:
    """Remove a license key from the stack by its JWT ``kid`` claim.

    Returns ``True`` if a key was removed, ``False`` if not found.
    """
    existing = get_server_license_keys()
    updated = []
    removed = False

    for key in existing:
        try:
            import jwt as _jwt
            header = _jwt.get_unverified_header(key)
            key_kid = header.get("kid") or _jwt.decode(
                key, options={"verify_signature": False}
            ).get("kid")
            if key_kid == kid:
                removed = True
                continue
        except Exception:
            pass
        updated.append(key)

    if removed:
        set_server_setting(_LICENSE_KEYS_SETTING, updated)
    return removed
