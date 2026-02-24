"""
License key validation for PGVectorRAGIndexer.

Determines the edition (Community vs Team) at runtime by reading
and validating a signed JWT license key from a platform-specific path.

This module is intentionally separate from config.py — the edition
is never stored in config or .env, it is always computed from the
license key.
"""

import enum
import json as _json
import logging
import os
import platform
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import jwt  # PyJWT
except ImportError:
    jwt = None  # Graceful fallback — Community edition if PyJWT not installed

logger = logging.getLogger(__name__)

# Environment variable for the HMAC signing secret
LICENSE_SECRET_ENV = "LICENSE_SIGNING_SECRET"

# Environment variable for optional online revocation endpoint
# When set, load_license() pings this URL on startup to check revocation.
# Example: https://api.ragvault.net/license/check
LICENSE_REVOCATION_URL_ENV = "LICENSE_REVOCATION_URL"

# Default license key file name
LICENSE_FILENAME = "license.key"

# Default Public Key for RS256 verification (Desktop Distribution)
# This allows distributed clients to validate licenses without a private secret.
PUBLIC_KEY_DEFAULT = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyD/JF2GcDga2usTBFKQs
nvyD/B4pA5NIrk5VxGR3xJqMUavUoUhvMaKG5pS4k7hxSBW7El7pO16rKx4uNwi
IX9EshqDl16i0+p3a8s/ZJGt257NdOxfrp+lCYMA6m9VFrXsigthx26b+sM1OgE4
v5DVF6hEUkx1BC7VF9/eEnt4M4a7GSXBsGIiFh2qea8RkMsciscqVgpSZU96mdMb
rjQeLZTBhmAVywIHsrjALMzfAeWpWsx05dhbV3PlTG5NJPhxDUZjZaYC6/eK8DZ+e
F9d3uteMoQd2F1dMU8FgBm6uaO7zY/gOxT9jU/xmwwpCoILEKa0ZeU7BYNZvTQW7
IQIDAQAB
-----END PUBLIC KEY-----"""


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
            "key_id": self.key_id,
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


def secure_license_file(key_path: Optional[Path] = None) -> bool:
    """Set restrictive file permissions on the license key file.

    - Linux/macOS: chmod 600 (owner read/write only)
    - Windows: best-effort — relies on user-profile ACLs

    Args:
        key_path: Path to the license file. Defaults to platform path.

    Returns:
        True if permissions were set successfully, False otherwise.
    """
    if key_path is None:
        key_path = get_license_file_path()

    if not key_path.exists():
        return False

    system = platform.system()
    if system == "Windows":
        # Windows: the file lives under %APPDATA% which is already
        # user-only by default. No extra action needed.
        logger.debug("Windows: relying on APPDATA ACLs for %s", key_path)
        return True

    # Linux / macOS: set 600
    try:
        import stat
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        # Also secure the directory (700)
        key_path.parent.chmod(stat.S_IRWXU)  # 0o700
        logger.debug("Set permissions 600 on %s", key_path)
        return True
    except OSError as e:
        logger.warning("Could not set permissions on %s: %s", key_path, e)
        return False


# ---------------------------------------------------------------------------
# Online revocation check
# ---------------------------------------------------------------------------


def check_license_revocation(
    key_id: str,
    revocation_url: str,
    timeout: float = 5.0,
) -> Optional[str]:
    """Check if a license key has been revoked via an online endpoint.

    This is an optional, best-effort check. On any failure (timeout,
    DNS error, HTTP error, malformed response), it returns None
    (treat as not revoked) so the app never blocks on network issues.

    Args:
        key_id: The license key ID (jti/kid claim from the JWT).
        revocation_url: Base URL of the revocation endpoint.
        timeout: HTTP timeout in seconds (default 5).

    Returns:
        None if not revoked or check failed/skipped.
        A revocation reason string if the key is revoked.
    """
    if not key_id or not revocation_url:
        return None

    # Build the check URL
    separator = "&" if "?" in revocation_url else "?"
    url = f"{revocation_url}{separator}kid={urllib.request.quote(key_id)}"

    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "PGVectorRAGIndexer-LicenseCheck/1.0")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096)  # Cap read size
            data = _json.loads(body)

            if data.get("revoked") is True:
                reason = data.get("reason", "License revoked")
                return str(reason)

        return None

    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        logger.debug("Revocation check failed (network): %s", e)
        return None
    except (ValueError, KeyError, _json.JSONDecodeError) as e:
        logger.debug("Revocation check failed (parse): %s", e)
        return None
    except Exception as e:
        logger.debug("Revocation check failed (unexpected): %s", e)
        return None


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------

# Required claims in a valid license JWT
REQUIRED_CLAIMS = {"edition", "org", "exp"}


def validate_license_key(
    key_string: str,
    signing_secret: str,
    allowed_algorithms: Optional[List[str]] = None,
) -> LicenseInfo:
    """Validate a license key string and return LicenseInfo.

    Args:
        key_string: The JWT license key string.
        signing_secret: Verification key — either an HMAC-SHA256 secret string
            or an RSA public key PEM. Should be pre-resolved by load_license();
            this function never reads os.environ directly.
        allowed_algorithms: Explicit list of JWT algorithms to accept. When None,
            the function falls back to legacy auto-detection (empty secret → RS256
            only; non-empty → HS256+RS256). Callers should always pass this
            explicitly — the auto-detection path is kept only for backward compat
            with direct callers of validate_license_key().

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

    if allowed_algorithms is not None:
        # Caller (load_license) has explicitly determined the correct algorithm
        # set based on which key source was used. Trust it.
        if not signing_secret:
            signing_secret = PUBLIC_KEY_DEFAULT
    else:
        # Legacy fallback: infer algorithm from whether a secret was supplied.
        # This path is kept for backward compat with direct callers only.
        if not signing_secret:
            signing_secret = PUBLIC_KEY_DEFAULT
            allowed_algorithms = ["RS256"]
        else:
            allowed_algorithms = ["HS256", "RS256"]

    try:
        # Decode and verify the JWT
        payload = jwt.decode(
            key_string.strip(),
            signing_secret,
            algorithms=allowed_algorithms,
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError:
        # Try decoding without expiry check to extract org name for a better message.
        # Use allowed_algorithms (not hardcoded HS256) so RS256 tokens also work.
        try:
            payload = jwt.decode(
                key_string.strip(),
                signing_secret,
                algorithms=allowed_algorithms,
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

    Key resolution priority (all env reads happen here, not in validate_license_key):
      1. LICENSE_PUBLIC_KEY env set → RS256 only (server operator override)
      2. LICENSE_SIGNING_SECRET env set → HS256 + RS256 (backward compat)
      3. Neither set → PUBLIC_KEY_DEFAULT hardcoded PEM → RS256 only (desktop clients)

    Args:
        signing_secret: Override the resolved key directly (used in tests). If None,
            the priority logic above applies.
        key_path: Override the license file path. If None, uses platform default.

    Returns:
        LicenseInfo with edition and details.
    """
    # Resolve signing secret and algorithm set via three-tier priority
    if signing_secret is None:
        public_key_env = os.environ.get("LICENSE_PUBLIC_KEY", "")
        hmac_secret_env = os.environ.get(LICENSE_SECRET_ENV, "")
        if public_key_env:
            # Tier 1: explicit public key override (server operators, key rotation)
            # RS256 ONLY — a public key must never allow HS256 verification
            signing_secret = public_key_env
            resolved_algorithms: Optional[List[str]] = ["RS256"]
        elif hmac_secret_env:
            # Tier 2: legacy HMAC secret — allow both for transition compatibility
            signing_secret = hmac_secret_env
            resolved_algorithms = ["HS256", "RS256"]
        else:
            # Tier 3: no env config — embedded public key, RS256 only (desktop clients)
            signing_secret = ""
            resolved_algorithms = ["RS256"]
    else:
        # Caller passed signing_secret directly (e.g., in tests); use legacy inference
        resolved_algorithms = None

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

    # Secure file permissions (best-effort, non-blocking)
    secure_license_file(key_path)

    if not key_string:
        logger.warning("License key file at %s is empty", key_path)
        return LicenseInfo(warning="License key file is empty")

    # Optional validation with signing secret or fallback to public key
    # If signing_secret is None, validate_license_key will use PUBLIC_KEY_DEFAULT.

    # Validate
    try:
        license_info = validate_license_key(key_string, signing_secret, resolved_algorithms)

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

        # Optional online revocation check
        revocation_url = os.environ.get(LICENSE_REVOCATION_URL_ENV, "")
        if revocation_url and license_info.is_team and license_info.key_id:
            reason = check_license_revocation(
                license_info.key_id, revocation_url
            )
            if reason:
                logger.warning(
                    "License %s revoked: %s",
                    license_info.key_id, reason,
                )
                return LicenseInfo(
                    warning=f"License revoked: {reason}"
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
