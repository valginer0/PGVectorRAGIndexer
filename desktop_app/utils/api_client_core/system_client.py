from typing import Dict, Any, Tuple
from packaging.version import Version, InvalidVersion
import logging

from desktop_app.utils.api_client_core.base_client import BaseAPIClient
from version import __version__ as CLIENT_VERSION

logger = logging.getLogger(__name__)

class SystemClient:
    """Domain client for system-level operations (health, version, statistics, license)."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client
        self._server_version = None

    def get_health(self) -> Dict[str, Any]:
        """Get the full health status of the API."""
        try:
            # Note: Health check specifically relies on `base_url`, not `api_base`
            response = self._base.request(
                "GET", 
                f"{self._base.base_url}/health", 
                timeout=5
            )
            return response.json()
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return {"status": "unreachable", "error": str(e)}

    def is_api_available(self) -> bool:
        """Check if the API is available (responding 200)."""
        health = self.get_health()
        return health.get("status") in ("healthy", "initializing")

    def check_version_compatibility(self) -> Tuple[bool, str]:
        """Check if this client version is compatible with the server."""
        try:
            # Note: Version check explicitly uses API base.
            response = self._base.request(
                "GET",
                f"{self._base.api_base}/version",
                timeout=5
            )
            data = response.json()
            self._server_version = data.get("server_version", "unknown")
            min_ver = data.get("min_client_version", "0.0.0")
            max_ver = data.get("max_client_version", "99.99.99")

            try:
                client_v = Version(CLIENT_VERSION)
                min_v = Version(min_ver)
                max_v = Version(max_ver)
            except InvalidVersion:
                return True, ""  # Can't parse — don't block

            if client_v < min_v:
                return False, (
                    f"This client (v{CLIENT_VERSION}) is too old for the server "
                    f"(v{self._server_version}). Minimum required: v{min_ver}. "
                    f"Please update the desktop app."
                )
            if client_v > max_v:
                return False, (
                    f"This client (v{CLIENT_VERSION}) is newer than the server "
                    f"(v{self._server_version}) supports. Maximum: v{max_ver}. "
                    f"Please update the server."
                )
            return True, ""
        except ImportError:
            logger.debug("packaging not installed, skipping version check")
            return True, ""
        except Exception:
            return True, ""  # Can't reach server — don't block

    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        response = self._base.request("GET", f"{self._base.api_base}/statistics")
        return response.json()

    def get_license_info(self) -> Dict[str, Any]:
        """Get license information from the server."""
        # Note: License endpoint relies on `base_url`, not `api_base`
        response = self._base.request(
            "GET",
            f"{self._base.base_url}/license",
            timeout=10
        )
        return response.json()

    def get_license_usage(self) -> Dict[str, Any]:
        """Get seat usage: licensed_seats, active_seats, overage.

        Returns a dict with keys ``licensed_seats``, ``active_seats``,
        ``overage``, and ``edition``.  Returns an empty dict on error so
        callers never raise.
        """
        try:
            response = self._base.request(
                "GET",
                f"{self._base.api_base}/license/usage",
                timeout=10,
            )
            return response.json()
        except Exception as e:
            logger.debug("get_license_usage failed: %s", e)
            return {}

    def install_server_license(self, license_key: str, action: str = "add") -> Dict[str, Any]:
        """Installs a license key on the server (`action` = "add" or "replace")."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/license/install",
            json={"license_key": license_key, "action": action},
            timeout=10,
        )
        return response.json()

    def list_server_licenses(self) -> Dict[str, Any]:
        """List all stacked server license keys (requires admin)."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/license/keys",
            timeout=10,
        )
        return response.json()

    def remove_server_license(self, kid: str) -> Dict[str, Any]:
        """Removes a server license key by its kid."""
        response = self._base.request(
            "DELETE",
            f"{self._base.api_base}/license/{kid}",
            timeout=10,
        )
        return response.json()
