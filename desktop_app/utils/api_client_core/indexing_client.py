from typing import Dict, Any, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class IndexingClient:
    """Domain client for indexing operations and runs."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def get_indexing_runs(self, limit: int = 20) -> Dict[str, Any]:
        """Get recent indexing runs."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/indexing/runs",
            params={"limit": limit}
        )
        return response.json()

    def get_indexing_summary(self) -> Dict[str, Any]:
        """Get aggregate indexing run statistics."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/indexing/runs/summary"
        )
        return response.json()

    def get_indexing_run_detail(self, run_id: str) -> Dict[str, Any]:
        """Get details of a single indexing run."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/indexing/runs/{run_id}"
        )
        return response.json()
