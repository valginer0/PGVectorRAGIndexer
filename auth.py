"""
API key authentication for PGVectorRAGIndexer.

Provides API key generation, hashing, verification, and a FastAPI
dependency for protecting endpoints. Auth is only enforced when
API_REQUIRE_AUTH=true — local mode stays unauthenticated.

This module is separate from license.py:
- API keys authenticate clients to the server (who can connect)
- License keys determine the edition (what features are available)
"""

import hashlib
import hmac
import ipaddress
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

# Key format constants
KEY_PREFIX = "pgv_sk_"
KEY_RANDOM_BYTES = 32  # 32 hex chars = 128 bits of randomness
GRACE_PERIOD_HOURS = 24  # Hours old key remains valid after rotation

# FastAPI security scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Loopback addresses (auth bypass in local mode)
LOOPBACK_ADDRS = {"127.0.0.1", "::1", "localhost"}


# ---------------------------------------------------------------------------
# Key generation and hashing
# ---------------------------------------------------------------------------


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash).
        full_key is shown to the user once; key_hash is stored server-side.
    """
    random_part = secrets.token_hex(KEY_RANDOM_BYTES)
    full_key = f"{KEY_PREFIX}{random_part}"
    key_hash = hash_api_key(full_key)
    return full_key, key_hash


def hash_api_key(key: str) -> str:
    """Compute SHA-256 hash of an API key.

    Args:
        key: The raw API key string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored hash (constant-time).

    Args:
        key: The raw API key from the request.
        stored_hash: The stored SHA-256 hash.

    Returns:
        True if the key matches.
    """
    computed = hash_api_key(key)
    return hmac.compare_digest(computed, stored_hash)


def get_key_prefix(key: str) -> str:
    """Extract the display prefix from a key (for identification).

    Returns the first 12 characters, e.g., 'pgv_sk_a1b2'.
    """
    return key[:12] if len(key) >= 12 else key


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def is_loopback_request(request: Request) -> bool:
    """Check if the request originates from a loopback address.

    This is used to determine whether auth should be enforced —
    local desktop connections are exempt.
    """
    client_host = request.client.host if request.client else None
    if not client_host:
        return False

    # Direct string match first
    if client_host in LOOPBACK_ADDRS:
        return True

    # IP address check for edge cases
    try:
        addr = ipaddress.ip_address(client_host)
        return addr.is_loopback
    except ValueError:
        return False


def is_auth_required(request: Request) -> bool:
    """Determine if authentication is required for this request.

    Auth is required when API_REQUIRE_AUTH=true, UNLESS the request
    originates from a loopback address (127.0.0.1 / ::1). This allows
    the local desktop app to work seamlessly while remote connections
    are still protected.

    When API_REQUIRE_AUTH is not set, auth is NOT required (local mode default).
    """
    from config import get_config
    config = get_config()
    if not getattr(config.api, 'require_auth', False):
        return False
    # Auth is enabled — but exempt loopback requests (local desktop app)
    if is_loopback_request(request):
        return False
    return True


# ---------------------------------------------------------------------------
# Key storage operations (database)
# ---------------------------------------------------------------------------


def _get_db_connection():
    """Get a raw database connection for key operations."""
    from database import get_db_manager
    return get_db_manager().get_connection()


def lookup_api_key(key_hash: str) -> Optional[dict]:
    """Look up an API key by its hash.

    Returns key record dict if found and active, None otherwise.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, key_prefix, created_at, last_used_at,
                   revoked_at, expires_at
            FROM api_keys
            WHERE key_hash = %s
              AND (revoked_at IS NULL OR revoked_at > NOW() - INTERVAL '%s hours')
              AND (expires_at IS NULL OR expires_at > NOW())
            """,
            (key_hash, GRACE_PERIOD_HOURS),
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "key_prefix": row[2],
                "created_at": row[3],
                "last_used_at": row[4],
                "revoked_at": row[5],
                "expires_at": row[6],
            }
        return None
    except Exception as e:
        logger.error("Failed to look up API key: %s", e)
        return None


def update_last_used(key_id: int) -> None:
    """Update the last_used_at timestamp for a key."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
            (key_id,),
        )
        conn.commit()
    except Exception as e:
        logger.debug("Failed to update last_used_at: %s", e)


def create_api_key_record(name: str) -> dict:
    """Create a new API key and store it in the database.

    Args:
        name: Human-readable name for this key (e.g., "Alice's laptop").

    Returns:
        Dict with 'key' (full key, show once), 'id', 'name', 'prefix', 'created_at'.
    """
    full_key, key_hash = generate_api_key()
    prefix = get_key_prefix(full_key)

    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO api_keys (name, key_hash, key_prefix)
        VALUES (%s, %s, %s)
        RETURNING id, created_at
        """,
        (name, key_hash, prefix),
    )
    row = cursor.fetchone()
    conn.commit()

    return {
        "key": full_key,  # Show ONCE
        "id": row[0],
        "name": name,
        "prefix": prefix,
        "created_at": str(row[1]),
    }


def list_api_keys() -> list[dict]:
    """List all API keys (never returns the hash or full key)."""
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, key_prefix, created_at, last_used_at,
               revoked_at, expires_at
        FROM api_keys
        ORDER BY created_at DESC
        """
    )
    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "prefix": row[2],
            "created_at": str(row[3]),
            "last_used_at": str(row[4]) if row[4] else None,
            "revoked_at": str(row[5]) if row[5] else None,
            "expires_at": str(row[6]) if row[6] else None,
            "active": row[5] is None and (row[6] is None or row[6] > datetime.now(timezone.utc)),
        }
        for row in rows
    ]


def revoke_api_key(key_id: int) -> bool:
    """Revoke an API key immediately.

    Returns True if a key was revoked.
    """
    conn = _get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE api_keys SET revoked_at = NOW() WHERE id = %s AND revoked_at IS NULL",
        (key_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def rotate_api_key(key_id: int) -> Optional[dict]:
    """Rotate an API key: create a new one, mark old as revoked with grace period.

    The old key remains valid for GRACE_PERIOD_HOURS after rotation.

    Returns new key info dict, or None if key_id not found.
    """
    conn = _get_db_connection()
    cursor = conn.cursor()

    # Get existing key info
    cursor.execute(
        "SELECT name FROM api_keys WHERE id = %s AND revoked_at IS NULL",
        (key_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    name = row[0]

    # Revoke old key (with grace period — lookup_api_key checks revoked_at + grace)
    cursor.execute(
        "UPDATE api_keys SET revoked_at = NOW() WHERE id = %s",
        (key_id,),
    )

    # Create new key
    full_key, key_hash = generate_api_key()
    prefix = get_key_prefix(full_key)
    cursor.execute(
        """
        INSERT INTO api_keys (name, key_hash, key_prefix)
        VALUES (%s, %s, %s)
        RETURNING id, created_at
        """,
        (f"{name} (rotated)", key_hash, prefix),
    )
    new_row = cursor.fetchone()
    conn.commit()

    return {
        "key": full_key,  # Show ONCE
        "id": new_row[0],
        "name": f"{name} (rotated)",
        "prefix": prefix,
        "created_at": str(new_row[1]),
        "old_key_id": key_id,
        "grace_period_hours": GRACE_PERIOD_HOURS,
    }


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def require_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[dict]:
    """FastAPI dependency that enforces API key auth when required.

    - If auth is not required (local mode), returns None.
    - If auth is required and key is valid, returns key record.
    - If auth is required and key is missing/invalid, raises 401.
    """
    if not is_auth_required(request):
        return None

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Include X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not api_key.startswith(KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = hash_api_key(api_key)
    key_record = lookup_api_key(key_hash)

    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Update last used (fire-and-forget, don't block the request)
    update_last_used(key_record["id"])

    return key_record


async def require_api_key_admin(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[dict]:
    """Same as require_api_key but specifically for key management endpoints.

    Key management endpoints always require auth when auth is enabled,
    to prevent unauthorized key creation.
    """
    return await require_api_key(request, api_key)


def require_permission(permission: str):
    """Factory that creates a FastAPI dependency requiring a specific permission.

    Usage:
        @router.delete("/documents/{id}", dependencies=[Depends(require_permission("documents.delete"))])

    The returned dependency:
    - If auth is not required (local mode), returns None (allow).
    - If auth is required, validates the API key AND checks that the
      linked user's role has the requested permission.
    - If no users exist yet (bootstrap), allows access.

    Upgrade path to Phase 4b (DB-backed RBAC):
    - Replace has_permission() in role_permissions.py to query a roles table.
    - This function stays unchanged.
    """
    async def _check_permission(
        request: Request,
        api_key: Optional[str] = Security(api_key_header),
    ) -> Optional[dict]:
        key_record = await require_api_key(request, api_key)

        # If auth is not enforced, allow
        if key_record is None:
            return None

        try:
            from users import get_user_by_api_key, count_admins
            from role_permissions import has_permission as _has_perm

            # Bootstrap: if no admin users exist yet, allow
            if count_admins() == 0:
                return key_record

            user = get_user_by_api_key(key_record["id"])
            if user and _has_perm(user.get("role", ""), permission):
                return key_record

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required.",
            )
        except HTTPException:
            raise
        except Exception as e:
            # Fail open ONLY if users table doesn't exist yet (bootstrap).
            # All other errors fail closed to prevent unauthorized access.
            err_str = str(e).lower()
            if "users" in err_str and ("not exist" in err_str or "undefined" in err_str or "no such" in err_str):
                logger.warning("Users table not found — allowing access (bootstrap): %s", e)
                return key_record
            logger.error("Permission check failed — denying access: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Permission check unavailable. Please try again later.",
            )

    return _check_permission


async def require_admin(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[dict]:
    """FastAPI dependency that requires the caller to be an admin user.

    - If auth is not required (local mode), returns None (allow).
    - If auth is required, validates the API key AND checks that the
      linked user has the 'admin' role (system.admin permission).
    - If no users exist yet (bootstrap), allows access so the first
      admin can be created.

    This is a convenience wrapper around require_permission("system.admin").
    """
    checker = require_permission("system.admin")
    return await checker(request, api_key)
