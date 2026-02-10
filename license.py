"""
License key validation for PGVectorRAGIndexer.

Determines the edition (Community vs Team) at runtime by reading
and validating a signed JWT license key from a platform-specific path.

This module is intentionally separate from config.py — the edition
is never stored in config or .env, it is always computed from the
license key.
"""

import enum
import logging
import os
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import jwt  # PyJWT
except ImportError:
    jwt = None  # Graceful fallback — Community edition if PyJWT not installed

logger = logging.getLogger(__name__)

# Environment variable for the HMAC signing secret
LICENSE_SECRET_ENV = "LICENSE_SIGNING_SECRET"

# Default license key file name
LICENSE_FILENAME = "license.key"


# ---------------------------------------------------------------------------
# Edition enum
# ---------------------------------------------------------------------------


class Edition(str, enum.Enum):
    """Product edition, determined by license key."""
    COMMUNITY = "community"
    TEAM = "team"


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class LicenseError(Exception):
    """Base class for license validation errors."""
    pass


class LicenseExpiredError(LicenseError):
    """License key has expired."""
    pass


class LicenseInvalidError(LicenseError):
    """License key is invalid (bad signature, malformed, etc.)."""
    pass


# ---------------------------------------------------------------------------
# LicenseInfo dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseInfo:
    """Information extracted from a validated license key."""

    edition: Edition = Edition.COMMUNITY
    org_name: str = ""
    seats: int = 0
    expiry_timestamp: float = 0.0
    issued_at: float = 0.0
    key_id: str = ""
    warning: str = ""

    @property
    def is_team(self) -> bool:
        """Check if this is a Team edition license."""
        return self.edition == Edition.TEAM

    @property
    def is_expired(self) -> bool:
        """Check if the license has expired."""
        if self.expiry_timestamp <= 0:
            return False  # No expiry = never expires (Community)
        return time.time() > self.expiry_timestamp

    @property
    def days_until_expiry(self) -> int:
        """Days remaining until license expires. Negative if already expired."""
        if self.expiry_timestamp <= 0:
            return 999  # No expiry
        remaining = self.expiry_timestamp - time.time()
        return int(remaining / 86400)

    def to_dict(self) -> dict:
        """Convert to a safe dict for API responses (no secrets)."""
        result = {
            "edition": self.edition.value,
            "org_name": self.org_name,
            "seats": self.seats,
            "days_until_expiry": self.days_until_expiry,
        }
        if self.warning:
            result["warning"] = self.warning
        return result


# Community edition singleton
COMMUNITY_LICENSE = LicenseInfo()


# ---------------------------------------------------------------------------
# Platform-specific paths
# ---------------------------------------------------------------------------


def get_license_file_path() -> Path:
    """Get the platform-specific license key file path.

    - Linux/macOS: ~/.pgvector-license/license.key
    - Windows: %APPDATA%/PGVectorRAGIndexer/license.key
    """
    system = platform.system()

    if system == "Windows":
        # Windows: %APPDATA%\PGVectorRAGIndexer\license.key
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "PGVectorRAGIndexer" / LICENSE_FILENAME
        # Fallback if APPDATA not set
        return Path.home() / "AppData" / "Roaming" / "PGVectorRAGIndexer" / LICENSE_FILENAME
    else:
        # Linux and macOS
        return Path.home() / ".pgvector-license" / LICENSE_FILENAME


def get_license_dir() -> Path:
    """Get the directory containing the license key file."""
    return get_license_file_path().parent


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------

# Required claims in a valid license JWT
REQUIRED_CLAIMS = {"edition", "org", "exp"}


def validate_license_key(key_string: str, signing_secret: str) -> LicenseInfo:
    """Validate a license key string and return LicenseInfo.

    Args:
        key_string: The JWT license key string.
        signing_secret: HMAC-SHA256 signing secret for verification.

    Returns:
        LicenseInfo with the validated license details.

    Raises:
        LicenseInvalidError: If the key is malformed or signature is invalid.
        LicenseExpiredError: If the key has expired.
        LicenseError: For other validation failures.
    """
    if jwt is None:
        raise LicenseError(
            "PyJWT is not installed. Install with: pip install PyJWT"
        )

    if not key_string or not key_string.strip():
        raise LicenseInvalidError("License key is empty")

    if not signing_secret:
        raise LicenseError("No signing secret configured")

    try:
        # Decode and verify the JWT
        payload = jwt.decode(
            key_string.strip(),
            signing_secret,
            algorithms=["HS256"],
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError:
        # Try decoding without expiry check to get the details
        try:
            payload = jwt.decode(
                key_string.strip(),
                signing_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            raise LicenseExpiredError(
                f"License for '{payload.get('org', 'unknown')}' expired"
            )
        except jwt.InvalidTokenError:
            raise LicenseExpiredError("License key has expired")
    except jwt.InvalidSignatureError:
        raise LicenseInvalidError("License key signature is invalid (tampered or wrong secret)")
    except jwt.DecodeError:
        raise LicenseInvalidError("License key is malformed (not a valid JWT)")
    except jwt.InvalidTokenError as e:
        raise LicenseInvalidError(f"License key is invalid: {e}")

    # Validate required fields
    edition_str = payload.get("edition", "").lower()
    if edition_str not in ("community", "team"):
        raise LicenseInvalidError(
            f"Invalid edition in license key: '{edition_str}'"
        )

    org_name = payload.get("org", "")
    if not org_name and edition_str == "team":
        raise LicenseInvalidError("Team license must include 'org' claim")

    # Build LicenseInfo
    return LicenseInfo(
        edition=Edition(edition_str),
        org_name=org_name,
        seats=int(payload.get("seats", 1)),
        expiry_timestamp=float(payload.get("exp", 0)),
        issued_at=float(payload.get("iat", 0)),
        key_id=str(payload.get("kid", payload.get("jti", ""))),
    )


# ---------------------------------------------------------------------------
# License loading
# ---------------------------------------------------------------------------


def load_license(
    signing_secret: Optional[str] = None,
    key_path: Optional[Path] = None,
) -> LicenseInfo:
    """Load and validate the license key from disk.

    This function never raises — it always returns a LicenseInfo.
    On any error, it returns Community edition with a warning.

    Args:
        signing_secret: HMAC signing secret. If None, reads from env.
        key_path: Override the license file path. If None, uses platform default.

    Returns:
        LicenseInfo with edition and details.
    """
    # Resolve signing secret
    if signing_secret is None:
        signing_secret = os.environ.get(LICENSE_SECRET_ENV, "")

    # Resolve key file path
    if key_path is None:
        key_path = get_license_file_path()

    # Check if key file exists
    if not key_path.exists():
        logger.info(
            "No license key found at %s — running as Community Edition",
            key_path,
        )
        return COMMUNITY_LICENSE

    # Read the key file
    try:
        key_string = key_path.read_text(encoding="utf-8").strip()
    except (OSError, IOError) as e:
        logger.warning("Could not read license key at %s: %s", key_path, e)
        return LicenseInfo(
            warning=f"Could not read license file: {e}"
        )

    if not key_string:
        logger.warning("License key file at %s is empty", key_path)
        return LicenseInfo(warning="License key file is empty")

    # No signing secret configured
    if not signing_secret:
        logger.warning(
            "License key found but %s is not set — cannot validate. "
            "Running as Community Edition.",
            LICENSE_SECRET_ENV,
        )
        return LicenseInfo(
            warning=f"License key found but {LICENSE_SECRET_ENV} is not set"
        )

    # Validate
    try:
        license_info = validate_license_key(key_string, signing_secret)

        # Check expiry (should already be caught by PyJWT, but double-check)
        if license_info.is_expired:
            logger.warning(
                "License for '%s' has expired. Running as Community Edition.",
                license_info.org_name,
            )
            return LicenseInfo(
                warning=f"Team license for '{license_info.org_name}' expired. "
                        f"Renew at https://ragvault.net/pricing"
            )

        logger.info(
            "License validated: %s Edition for '%s' (%d seats, %d days remaining)",
            license_info.edition.value.title(),
            license_info.org_name,
            license_info.seats,
            license_info.days_until_expiry,
        )

        # Warn if expiring soon (< 14 days)
        if 0 < license_info.days_until_expiry <= 14:
            return LicenseInfo(
                edition=license_info.edition,
                org_name=license_info.org_name,
                seats=license_info.seats,
                expiry_timestamp=license_info.expiry_timestamp,
                issued_at=license_info.issued_at,
                key_id=license_info.key_id,
                warning=f"License expires in {license_info.days_until_expiry} days. "
                        f"Renew at https://ragvault.net/pricing",
            )

        return license_info

    except LicenseExpiredError as e:
        logger.warning("License expired: %s", e)
        return LicenseInfo(warning=str(e))

    except LicenseInvalidError as e:
        logger.warning("Invalid license key: %s", e)
        return LicenseInfo(warning=str(e))

    except LicenseError as e:
        logger.warning("License error: %s", e)
        return LicenseInfo(warning=str(e))

    except Exception as e:
        logger.error("Unexpected error validating license: %s", e)
        return LicenseInfo(warning=f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Global license state
# ---------------------------------------------------------------------------

_current_license: Optional[LicenseInfo] = None


def get_current_license() -> LicenseInfo:
    """Get the current license info, loading from disk on first call.

    Returns:
        LicenseInfo for the current session.
    """
    global _current_license
    if _current_license is None:
        _current_license = load_license()
    return _current_license


def set_current_license(license_info: LicenseInfo) -> None:
    """Set the current license (used by startup and tests)."""
    global _current_license
    _current_license = license_info


def reset_license() -> None:
    """Reset cached license (forces reload on next access)."""
    global _current_license
    _current_license = None


def is_team_edition() -> bool:
    """Convenience check: is the current edition Team?"""
    return get_current_license().is_team
