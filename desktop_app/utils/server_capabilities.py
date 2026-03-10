"""
Centralized server capability detection for the Organization console.

Probes server endpoints once per session and caches results.
UNREACHABLE is never cached (transient network failure).
All other statuses are cached until explicit invalidation.
"""

import logging
from typing import Dict, Optional

from desktop_app.utils.api_client import APIClient, CapabilityStatus, ProbeResult

logger = logging.getLogger(__name__)

# Endpoints to probe (all GET, read-only, no side effects)
_PROBES: Dict[str, str] = {
    "me":          "/api/v1/me",
    "users":       "/api/v1/users?limit=1&active_only=true",
    "roles":       "/api/v1/roles",
    "permissions": "/api/v1/permissions",
    "retention":   "/api/v1/retention/policy",
    "activity":    "/api/v1/activity?limit=1",
}


class ServerCapabilities:
    """Probes server endpoints and caches capability results.

    Usage:
        caps = ServerCapabilities(api_client)
        caps.probe_all()
        if caps.is_available("users"):
            data = api_client.list_users()
        if caps.is_admin():
            # show write controls
    """

    def __init__(self, api_client: APIClient):
        self._api_client = api_client
        self._cache: Dict[str, CapabilityStatus] = {}
        self._me_response: Optional[dict] = None
        self._probe_errors: Dict[str, Optional[str]] = {}
        self._probing = False

    def probe_all(self) -> Dict[str, CapabilityStatus]:
        """Probe all endpoints. Returns full status dict.

        Guarded by _probing flag (cleared in finally) to prevent
        redundant burst requests.
        """
        if self._probing:
            return {k: self._cache.get(k, CapabilityStatus.UNKNOWN) for k in _PROBES}

        self._probing = True
        try:
            for name, path in _PROBES.items():
                result = self._api_client.probe_endpoint(path)

                # Never cache UNREACHABLE — transient failure
                if result.status != CapabilityStatus.UNREACHABLE:
                    self._cache[name] = result.status
                    self._probe_errors[name] = result.error_message

                    # Cache /me response for admin detection
                    if name == "me" and result.status == CapabilityStatus.AVAILABLE and result.body:
                        self._me_response = result.body
                else:
                    # Don't update cache — preserve previous value if any
                    self._probe_errors[name] = result.error_message
        finally:
            self._probing = False

        return {k: self._cache.get(k, CapabilityStatus.UNKNOWN) for k in _PROBES}

    def get(self, capability: str) -> CapabilityStatus:
        """Return cached status for a capability, or UNKNOWN if not probed."""
        return self._cache.get(capability, CapabilityStatus.UNKNOWN)

    def is_available(self, capability: str) -> bool:
        """Shorthand for get(cap) == AVAILABLE."""
        return self.get(capability) == CapabilityStatus.AVAILABLE

    def get_error(self, capability: str) -> Optional[str]:
        """Return cached error message for a capability, if any."""
        return self._probe_errors.get(capability)

    def is_admin(self) -> bool:
        """Check if the current user has system.admin permission.

        Based on cached /me response. Returns False if /me was not
        probed or not available.
        """
        if not self._me_response:
            return False
        perms = self._me_response.get("permissions", [])
        return "system.admin" in perms

    def get_identity(self) -> Optional[dict]:
        """Return cached /me response, or None if not available."""
        return self._me_response

    def invalidate(self):
        """Clear all cached state. Called on settings change."""
        self._cache.clear()
        self._me_response = None
        self._probe_errors.clear()

    def any_available(self) -> bool:
        """True if at least one capability (excluding 'me') is AVAILABLE."""
        return any(
            self._cache.get(k) == CapabilityStatus.AVAILABLE
            for k in _PROBES
            if k != "me"
        )

    def any_unauthorized(self) -> bool:
        """True if at least one capability (excluding 'me') returned UNAUTHORIZED."""
        return any(
            self._cache.get(k) == CapabilityStatus.UNAUTHORIZED
            for k in _PROBES
            if k != "me"
        )

    def all_unreachable_or_unknown(self) -> bool:
        """True if no capability has been successfully cached."""
        for name in _PROBES:
            status = self._cache.get(name)
            if status is not None and status != CapabilityStatus.UNKNOWN:
                return False
        return True
