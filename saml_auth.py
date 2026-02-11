"""
SAML/SSO authentication module for #16 Enterprise Foundations (Phase 2).

Provides Okta (and generic SAML 2.0 IdP) integration:
- SP metadata generation
- SAML AuthnRequest initiation
- Assertion Consumer Service (ACS) callback handling
- Single Logout (SLO)
- Session management (create, validate, expire)
- Auto-provisioning of users on first SAML login

Configuration is via environment variables:
    SAML_ENABLED=true
    SAML_IDP_ENTITY_ID=https://your-okta-domain.okta.com/...
    SAML_IDP_SSO_URL=https://your-okta-domain.okta.com/app/.../sso/saml
    SAML_IDP_SLO_URL=https://your-okta-domain.okta.com/app/.../slo/saml  (optional)
    SAML_IDP_X509_CERT=<base64 cert from Okta>
    SAML_SP_ENTITY_ID=https://your-app-domain/api/v1/saml/metadata
    SAML_SP_ACS_URL=https://your-app-domain/api/v1/saml/acs
    SAML_SP_SLS_URL=https://your-app-domain/api/v1/saml/sls  (optional)
    SAML_SESSION_LIFETIME_HOURS=8  (default: 8)
    SAML_AUTO_PROVISION=true  (default: true)
    SAML_DEFAULT_ROLE=user  (default: user)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAML_ENABLED = os.environ.get("SAML_ENABLED", "false").lower() in ("true", "1", "yes")

SAML_IDP_ENTITY_ID = os.environ.get("SAML_IDP_ENTITY_ID", "")
SAML_IDP_SSO_URL = os.environ.get("SAML_IDP_SSO_URL", "")
SAML_IDP_SLO_URL = os.environ.get("SAML_IDP_SLO_URL", "")
SAML_IDP_X509_CERT = os.environ.get("SAML_IDP_X509_CERT", "")

SAML_SP_ENTITY_ID = os.environ.get("SAML_SP_ENTITY_ID", "")
SAML_SP_ACS_URL = os.environ.get("SAML_SP_ACS_URL", "")
SAML_SP_SLS_URL = os.environ.get("SAML_SP_SLS_URL", "")

SAML_SESSION_LIFETIME_HOURS = int(os.environ.get("SAML_SESSION_LIFETIME_HOURS", "8"))
SAML_AUTO_PROVISION = os.environ.get("SAML_AUTO_PROVISION", "true").lower() in ("true", "1", "yes")
SAML_DEFAULT_ROLE = os.environ.get("SAML_DEFAULT_ROLE", "user")

# ---------------------------------------------------------------------------
# Optional import — python3-saml may not be installed
# ---------------------------------------------------------------------------

_saml_available = False
try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    from onelogin.saml2.utils import OneLogin_Saml2_Utils
    _saml_available = True
except ImportError:
    logger.info("python3-saml not installed — SAML/SSO features disabled.")


def is_saml_available() -> bool:
    """Return True if SAML is both enabled and the library is installed."""
    return SAML_ENABLED and _saml_available


# ---------------------------------------------------------------------------
# python3-saml settings builder
# ---------------------------------------------------------------------------


def _build_saml_settings() -> dict:
    """Build the settings dict expected by python3-saml."""
    settings = {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": SAML_SP_ENTITY_ID,
            "assertionConsumerService": {
                "url": SAML_SP_ACS_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            "entityId": SAML_IDP_ENTITY_ID,
            "singleSignOnService": {
                "url": SAML_IDP_SSO_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": SAML_IDP_X509_CERT,
        },
        "security": {
            "nameIdEncrypted": False,
            "authnRequestsSigned": False,
            "logoutRequestSigned": False,
            "logoutResponseSigned": False,
            "signMetadata": False,
            "wantMessagesSigned": True,
            "wantAssertionsSigned": True,
            "wantNameIdEncrypted": False,
            "wantAttributeStatement": False,
        },
    }

    # Optional SLO
    if SAML_SP_SLS_URL:
        settings["sp"]["singleLogoutService"] = {
            "url": SAML_SP_SLS_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }
    if SAML_IDP_SLO_URL:
        settings["idp"]["singleLogoutService"] = {
            "url": SAML_IDP_SLO_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    return settings


def prepare_request_from_fastapi(request_obj) -> dict:
    """Convert a FastAPI/Starlette Request into the dict python3-saml expects.

    Args:
        request_obj: A FastAPI Request object.

    Returns:
        Dict with http_host, script_name, get_data, post_data, etc.
    """
    url = request_obj.url
    return {
        "http_host": url.hostname or "localhost",
        "script_name": url.path,
        "get_data": dict(request_obj.query_params),
        "post_data": {},  # Will be populated for ACS
        "https": "on" if url.scheme == "https" else "off",
        "server_port": str(url.port or (443 if url.scheme == "https" else 80)),
    }


def get_saml_auth(request_dict: dict) -> "OneLogin_Saml2_Auth":
    """Create a OneLogin_Saml2_Auth instance from a request dict."""
    if not _saml_available:
        raise RuntimeError("python3-saml is not installed")
    settings = _build_saml_settings()
    return OneLogin_Saml2_Auth(request_dict, old_settings=settings)


# ---------------------------------------------------------------------------
# SP Metadata
# ---------------------------------------------------------------------------


def get_sp_metadata() -> str:
    """Generate SP metadata XML for configuring the IdP (Okta)."""
    if not _saml_available:
        raise RuntimeError("python3-saml is not installed")
    settings = _build_saml_settings()
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    saml_settings = OneLogin_Saml2_Settings(settings=settings, sp_validation_only=True)
    metadata = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(metadata)
    if errors:
        logger.error("SP metadata validation errors: %s", errors)
    return metadata.decode("utf-8") if isinstance(metadata, bytes) else metadata


# ---------------------------------------------------------------------------
# Login initiation
# ---------------------------------------------------------------------------


def initiate_login(request_dict: dict, return_to: str = None) -> str:
    """Start the SAML login flow — returns the redirect URL to the IdP.

    Args:
        request_dict: Output of prepare_request_from_fastapi().
        return_to: Optional URL to redirect to after successful login.

    Returns:
        The IdP SSO URL with the SAML AuthnRequest.
    """
    auth = get_saml_auth(request_dict)
    return auth.login(return_to=return_to)


# ---------------------------------------------------------------------------
# ACS (Assertion Consumer Service) — process IdP response
# ---------------------------------------------------------------------------


def process_acs(request_dict: dict, post_data: dict) -> dict:
    """Process the SAML response from the IdP after user authentication.

    Args:
        request_dict: Output of prepare_request_from_fastapi().
        post_data: The POST form data containing SAMLResponse.

    Returns:
        Dict with keys: success, email, display_name, name_id, name_id_format,
        session_index, errors.
    """
    request_dict["post_data"] = post_data
    auth = get_saml_auth(request_dict)
    auth.process_response()
    errors = auth.get_errors()

    if errors:
        logger.error("SAML ACS errors: %s (reason: %s)", errors, auth.get_last_error_reason())
        return {
            "success": False,
            "errors": errors,
            "error_reason": auth.get_last_error_reason(),
        }

    if not auth.is_authenticated():
        return {
            "success": False,
            "errors": ["User not authenticated"],
            "error_reason": "Authentication failed",
        }

    # Extract attributes
    attrs = auth.get_attributes()
    name_id = auth.get_nameid()
    name_id_format = auth.get_nameid_format()
    session_index = auth.get_session_index()

    # Try to get email and display name from attributes or NameID
    email = None
    display_name = None

    # Common Okta attribute names
    email_attrs = [
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        "email",
        "Email",
        "User.email",
    ]
    name_attrs = [
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "displayName",
        "display_name",
        "User.FirstName",
    ]

    for attr in email_attrs:
        vals = attrs.get(attr, [])
        if vals:
            email = vals[0]
            break
    if not email and name_id and "@" in name_id:
        email = name_id

    for attr in name_attrs:
        vals = attrs.get(attr, [])
        if vals:
            display_name = vals[0]
            break

    return {
        "success": True,
        "email": email,
        "display_name": display_name,
        "name_id": name_id,
        "name_id_format": name_id_format,
        "session_index": session_index,
        "attributes": {k: v for k, v in attrs.items()},
        "errors": [],
    }


# ---------------------------------------------------------------------------
# SLO (Single Logout)
# ---------------------------------------------------------------------------


def initiate_logout(request_dict: dict, name_id: str, session_index: str = None) -> str:
    """Start the SAML logout flow — returns the redirect URL to the IdP.

    Args:
        request_dict: Output of prepare_request_from_fastapi().
        name_id: The NameID from the SAML session.
        session_index: Optional session index from the SAML session.

    Returns:
        The IdP SLO URL with the SAML LogoutRequest.
    """
    auth = get_saml_auth(request_dict)
    return auth.logout(name_id=name_id, session_index=session_index)


def process_slo(request_dict: dict) -> dict:
    """Process the SLO response from the IdP.

    Returns:
        Dict with keys: success, errors.
    """
    auth = get_saml_auth(request_dict)
    auth.process_slo()
    errors = auth.get_errors()
    if errors:
        logger.error("SAML SLO errors: %s", errors)
        return {"success": False, "errors": errors}
    return {"success": True, "errors": []}


# ---------------------------------------------------------------------------
# Session management (DB-backed)
# ---------------------------------------------------------------------------


def _get_db_connection():
    """Get a database connection from the global DB manager."""
    from database import get_db_manager
    db = get_db_manager()
    return db.get_connection()


def create_session(
    user_id: str,
    name_id: str,
    name_id_format: str = None,
    session_index: str = None,
    idp_entity_id: str = None,
) -> Optional[dict]:
    """Create a new SAML session in the database.

    Returns:
        Session dict or None on failure.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SAML_SESSION_LIFETIME_HOURS)
        cursor.execute(
            """
            INSERT INTO saml_sessions (user_id, session_index, name_id, name_id_format,
                                       idp_entity_id, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, session_index, name_id, name_id_format,
                      idp_entity_id, created_at, expires_at, is_active
            """,
            (user_id, session_index, name_id, name_id_format,
             idp_entity_id or SAML_IDP_ENTITY_ID, expires_at),
        )
        row = cursor.fetchone()
        conn.commit()
        if row:
            return _session_row_to_dict(row)
        return None
    except Exception as e:
        logger.error("Failed to create SAML session: %s", e)
        return None


def get_session(session_id: str) -> Optional[dict]:
    """Get a SAML session by ID, only if active and not expired."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, session_index, name_id, name_id_format,
                   idp_entity_id, created_at, expires_at, is_active
            FROM saml_sessions
            WHERE id = %s AND is_active = true AND expires_at > now()
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row:
            return _session_row_to_dict(row)
        return None
    except Exception as e:
        logger.error("Failed to get SAML session: %s", e)
        return None


def expire_session(session_id: str) -> bool:
    """Mark a SAML session as inactive."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE saml_sessions SET is_active = false WHERE id = %s",
            (session_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error("Failed to expire SAML session: %s", e)
        return False


def expire_user_sessions(user_id: str) -> int:
    """Expire all active sessions for a user. Returns count of expired sessions."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE saml_sessions SET is_active = false WHERE user_id = %s AND is_active = true",
            (user_id,),
        )
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error("Failed to expire user sessions: %s", e)
        return 0


def cleanup_expired_sessions() -> int:
    """Remove expired sessions from the database. Returns count deleted."""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM saml_sessions WHERE expires_at < now() OR is_active = false"
        )
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        logger.error("Failed to cleanup expired sessions: %s", e)
        return 0


def _session_row_to_dict(row) -> dict:
    """Convert a saml_sessions row tuple to a dict."""
    keys = [
        "id", "user_id", "session_index", "name_id", "name_id_format",
        "idp_entity_id", "created_at", "expires_at", "is_active",
    ]
    d = dict(zip(keys, row))
    for ts_key in ("created_at", "expires_at"):
        val = d.get(ts_key)
        if val and hasattr(val, "isoformat"):
            d[ts_key] = val.isoformat()
    return d


# ---------------------------------------------------------------------------
# Auto-provisioning
# ---------------------------------------------------------------------------


def provision_or_get_user(email: str, display_name: str = None) -> Optional[dict]:
    """Find an existing user by email, or auto-provision a new one.

    Auto-provisioning creates a user with auth_provider='saml' and the
    configured default role.

    Returns:
        User dict or None on failure.
    """
    from users import get_user_by_email, create_user, record_login, AUTH_PROVIDER_SAML

    user = get_user_by_email(email)
    if user:
        record_login(user["id"])
        return user

    if not SAML_AUTO_PROVISION:
        logger.warning("SAML auto-provision disabled; no user for email=%s", email)
        return None

    user = create_user(
        email=email,
        display_name=display_name,
        role=SAML_DEFAULT_ROLE,
        auth_provider=AUTH_PROVIDER_SAML,
    )
    if user:
        logger.info("Auto-provisioned SAML user: %s (role=%s)", email, SAML_DEFAULT_ROLE)
        record_login(user["id"])
    return user
