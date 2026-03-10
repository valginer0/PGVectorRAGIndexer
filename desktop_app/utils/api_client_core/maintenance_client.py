from typing import Dict, Any

from desktop_app.utils.api_client_core.base_client import BaseAPIClient


class MaintenanceClient:
    """Domain client for maintenance/system endpoints (retention, quarantine)."""

    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def get_retention_policy(self) -> Dict[str, Any]:
        """Get the effective retention policy defaults."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/retention/policy"
        )
        return response.json()

    def get_retention_status(self) -> Dict[str, Any]:
        """Get retention execution status (last run, next run, etc.)."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/retention/status"
        )
        return response.json()
