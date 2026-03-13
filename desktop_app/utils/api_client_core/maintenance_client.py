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

    def run_retention(
        self,
        *,
        activity_days: int = None,
        quarantine_days: int = None,
        indexing_runs_days: int = None,
        cleanup_saml_sessions: bool = True,
    ) -> Dict[str, Any]:
        """Run a one-off retention cycle with the given parameters."""
        body = {"cleanup_saml_sessions": cleanup_saml_sessions}
        if activity_days is not None:
            body["activity_days"] = activity_days
        if quarantine_days is not None:
            body["quarantine_days"] = quarantine_days
        if indexing_runs_days is not None:
            body["indexing_runs_days"] = indexing_runs_days
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/retention/run",
            json=body,
        )
        return response.json()

    def export_compliance_report(self) -> bytes:
        """Download the compliance report ZIP file."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/compliance/export",
            timeout=60,
        )
        return response.content
