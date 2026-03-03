from typing import Dict, Any, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class SearchClient:
    """Domain client for search operations."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.5,
        metric: str = "cosine",
        document_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> list:
        """Search the indexed documents."""
        payload = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "metric": metric,
            "use_hybrid": True
        }
        
        if filters:
            payload["filters"] = filters
        elif document_type:
            payload["filters"] = {"type": document_type}
            
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/search",
            json=payload
        )
        data = response.json()
        return data.get("results", [])
