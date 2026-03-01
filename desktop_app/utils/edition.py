"""
Edition helpers for the desktop UI.

Thin wrapper around license.py for feature gating in the desktop app.
Provides a feature→edition map and helpers to check availability.
"""

import logging
import webbrowser
from typing import Optional

from license import Edition, LicenseInfo, get_current_license

from license_utils import compute_days_until_expiry
from desktop_app.utils.license_dto import LicenseDisplayDTO

logger = logging.getLogger(__name__)

# URL for the pricing / upgrade page
PRICING_URL = "https://ragvault.net/#pricing"

# Map of Team-only features to their descriptions.
# Used by GatedFeatureWidget and is_feature_available().
TEAM_FEATURES: dict[str, str] = {
    "scheduled_indexing": "Automatically re-index watched folders on a schedule.",
    "multi_user": "Multiple desktop clients sharing one backend.",
    "split_deployment": "Separate server backend from desktop clients.",
    "remote_backend": "Connect the desktop app to a remote server.",
    "audit_log": "Track who indexed what and when.",
    "client_identity": "Per-client identity and sync status.",
    "path_mapping": "Virtual roots for cross-platform path resolution.",
    "rbac": "Role-based access control (Admin / User roles).",
    "sso": "Single sign-on via SAML (Okta, Azure AD).",
}


def is_feature_available(feature_name: str) -> bool:
    """Check if a feature is available in the current edition.

    Community features are always available.
    Team features require a valid Team license.

    Args:
        feature_name: Key from TEAM_FEATURES, or any string.
            If the name is not in TEAM_FEATURES, it is assumed
            to be a Community feature (always available).

    Returns:
        True if the feature is available.
    """
    if feature_name not in TEAM_FEATURES:
        return True  # Not gated → always available

    license_info = get_current_license()
    return license_info.is_team


def get_edition_display(data: Optional[dict] = None) -> LicenseDisplayDTO:
    """Get edition information formatted for the UI.

    If data is provided, it is used instead of the local license.
    Returns a LicenseDisplayDTO.
    """
    if data:
        # Server mode
        is_paid = data.get("edition") in ("team", "organization")
        edition_name = data.get("edition", "community").title()
        prefix = "Server Edition: "
        org_name = data.get("org_name", "")
        # Defensive coercion - trust server types but guard against malformed data
        try:
            seats = int(data.get("seats", 0))
        except (ValueError, TypeError):
            seats = 0
            
        # TRUST SERVER - do not recompute from timestamps
        days_val = data.get("days_until_expiry")
        try:
            days_left = int(days_val) if days_val is not None else None
        except (ValueError, TypeError):
            days_left = None
            
        warning = data.get("warning", "")
    else:
        # Local mode
        info = get_current_license()
        is_paid = info.is_team
        edition_name = info.edition.value.title()
        prefix = ""
        org_name = info.org_name or ""
        seats = info.seats
        # Local computation using license_utils
        days_left = compute_days_until_expiry(info.expiry_timestamp)
        warning = info.warning or ""

    expiry_warning = False
    if is_paid and days_left is not None and 0 < days_left <= 30:
        expiry_warning = True

    return LicenseDisplayDTO(
        edition_label=f"{prefix}{edition_name} Edition",
        is_team=is_paid,
        org_name=org_name,
        seats=seats,
        days_left=days_left,
        expiry_warning=expiry_warning,
        warning_text=warning,
    )


def is_write_allowed() -> bool:
    """Check if write operations are allowed under the current license.

    Graceful degradation policy:
    - Community edition: writes always allowed (no license needed)
    - Team edition (valid): writes allowed
    - Team edition (expired): writes BLOCKED — read-only fallback

    The "expired Team" case is detected by checking if the license
    warning text mentions expiry while the edition fell back to Community.
    """
    info = get_current_license()

    # Valid Team license → writes allowed
    if info.is_team:
        return True

    # Community (no license ever) → writes allowed
    if not info.warning:
        return True

    # Has a warning — check if it's an expiry warning
    warning_lower = (info.warning or "").lower()
    if "expired" in warning_lower:
        return False  # Expired Team → read-only

    # Other warnings (e.g., missing secret, invalid key) → allow writes
    return True


def open_pricing_page() -> None:
    """Open the pricing page in the default browser."""
    webbrowser.open(PRICING_URL)
