from typing import List, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class MetadataClient:
    """Domain client for metadata keys and values extraction."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def get_metadata_keys(self, pattern: Optional[str] = None) -> List[str]:
        """Get all unique metadata keys."""
        params = {}
        if pattern:
            params["pattern"] = pattern
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/metadata/keys",
            params=params
        )
        return response.json()

    def get_metadata_values(self, key: str) -> List[str]:
        """Get all unique values for a specific metadata key."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/metadata/values",
            params={"key": key}
        )
        return response.json()
