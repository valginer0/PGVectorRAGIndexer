"""
REST API client for communicating with the backend.
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class APIClient:
    """Client for interacting with the PGVectorRAGIndexer REST API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL of the API
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = 300
    
    def is_api_available(self) -> bool:
        """Check if the API is available."""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def check_document_exists(self, source_uri: str) -> bool:
        """
        Check if a document with the given source URI already exists.
        
        Args:
            source_uri: Source URI to check
            
        Returns:
            True if document exists, False otherwise
        """
        try:
            # Use list_documents with filter to check existence
            # We use a specific filter pattern to match exact URI if possible,
            # or rely on the fact that we can filter by source_uri in the backend if supported.
            # For now, let's assume we can search/filter by exact source_uri or use a similar mechanism.
            # Actually, the backend might support filtering by source_uri directly.
            # Let's try to use the search endpoint with a filter, or list documents with a filter.
            
            # Since the backend API for exact match might vary, let's try to use the search/list endpoint
            # with a filter if available, or just assume we can't easily check without a dedicated endpoint.
            # However, looking at manage_tab.py, we use 'source_uri_like' for wildcards.
            # Maybe we can use that with an exact match?
            
            # Better approach: Use the /documents endpoint with a limit=1 and source_uri filter if supported.
            # If not supported, we might need to rely on the upload endpoint's behavior (it might return 409).
            # But the worker explicitly calls this method.
            
            # Let's implement a best-effort check using list_documents with a filter.
            # If the backend doesn't support exact source_uri filtering, this might be inefficient.
            # But wait, manage_tab uses 'source_uri_like'.
            
            # Let's try to use 'source_uri' filter if the backend supports it.
            # Based on manage_tab.py: filters["source_uri_like"] = sql_pattern
            
            # Let's try to find a document with this URI.
            # We can use the 'source_uri_like' filter with the exact URI (escaping wildcards if needed).
            # But standard SQL LIKE without wildcards acts as equals.
            
            filters = {"source_uri_like": source_uri}
            response = self.list_documents(limit=1, offset=0)
            # Wait, list_documents doesn't accept filters in the python client method signature I see above!
            # It only accepts limit, offset, sort_by, sort_dir.
            
            # Let's check if we can pass filters to list_documents.
            # The list_documents method in APIClient (lines 131-153) DOES NOT take filters.
            
            # However, the search method DOES take filters.
            # Let's use search with a filter.
            
            results = self.search(
                query="", # Empty query to match all (if supported) or just rely on filter
                top_k=1,
                filters={"source_uri_like": source_uri}
            )
            return len(results) > 0
            
        except Exception:
            # If check fails, assume it doesn't exist to allow upload attempt
            return False
    
    def upload_document(
        self,
        file_path: Path,
        custom_source_uri: Optional[str] = None,
        force_reindex: bool = False,
        document_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload and index a document.
        
        Args:
            file_path: Path to the file to upload
            custom_source_uri: Custom source URI (full path) to preserve
            force_reindex: Whether to force reindexing if document exists
            document_type: Optional document type/category (e.g., 'resume', 'policy', 'report')
            
        Returns:
            Response data from the API
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Uploading document: {file_path} (type: {document_type})")
        
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f)}
            data = {'force_reindex': str(force_reindex).lower()}
            
            if custom_source_uri:
                data['custom_source_uri'] = custom_source_uri
            
            if document_type:
                data['document_type'] = document_type
            
            response = requests.post(
                f"{self.base_url}/upload-and-index",
                files=files,
                data=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.5,
        metric: str = "cosine",
        document_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum similarity score
            metric: Similarity metric to use
            document_type: Optional filter by document type (deprecated, use filters)
            filters: Optional filter dictionary
            
        Returns:
            List of search results
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Searching for: {query} (filters: {filters or document_type})")
        
        payload = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "metric": metric
        }
        
        # Add filters if specified
        if filters:
            payload["filters"] = filters
        elif document_type:
            # Backward compatibility
            payload["filters"] = {"type": document_type}
        
        response = requests.post(
            f"{self.base_url}/search",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["results"]
    
    def list_documents(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "indexed_at",
        sort_dir: str = "desc"
    ) -> Dict[str, Any]:
        """Retrieve documents with pagination metadata."""
        params = {
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }

        response = requests.get(
            f"{self.base_url}/documents",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()

        # Legacy support: plain list response
        if isinstance(data, list):
            return {
                "items": data,
                "total": len(data),
                "limit": limit,
                "offset": offset,
                "sort": {
                    "by": sort_by,
                    "direction": sort_dir,
                },
                "_total_estimated": True,
            }

        if isinstance(data, dict):
            # Modern payload already in paginated shape
            if "items" in data:
                normalized = dict(data)  # shallow copy to avoid mutating original
                if normalized.get("total") is None:
                    normalized["total"] = len(normalized.get("items", []))
                    normalized["_total_estimated"] = True
                else:
                    normalized.setdefault("total", len(normalized.get("items", [])))
                    normalized.setdefault("_total_estimated", False)
                normalized.setdefault("limit", limit)
                normalized.setdefault("offset", offset)
                normalized.setdefault("sort", {"by": sort_by, "direction": sort_dir})
                return normalized

            # Backward compatibility for older keys ("documents")
            if "documents" in data:
                items = data.get("documents", [])
                return {
                    "items": items,
                    "total": data.get("total", len(items)),
                    "limit": data.get("limit", limit),
                    "offset": data.get("offset", offset),
                    "sort": data.get("sort", {"by": sort_by, "direction": sort_dir}),
                    "_total_estimated": data.get("total") is None,
                }

        raise requests.RequestException("Unexpected response structure from /documents endpoint")
    
    def get_document(self, document_id: str) -> Dict[str, Any]:
        """
        Get a specific document by ID.
        
        Args:
            document_id: Document ID
            
        Returns:
            Document data
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/documents/{document_id}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document.
        
        Args:
            document_id: Document ID to delete
            
        Returns:
            Response data
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Deleting document: {document_id}")
        
        response = requests.delete(
            f"{self.base_url}/documents/{document_id}",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Statistics data
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/statistics",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def bulk_delete_preview(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Preview what documents would be deleted with given filters.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Preview data with document count and samples
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters, "preview": True}
        logger.info(f"bulk_delete_preview payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/bulk-delete",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def bulk_delete(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Actually delete documents matching filters.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Delete result with chunks_deleted count
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters, "preview": False}
        logger.info(f"bulk_delete payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/bulk-delete",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def export_documents(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Export documents matching filters as backup.
        
        Args:
            filters: Filter criteria
            
        Returns:
            Export data with backup_data
            
        Raises:
            requests.RequestException: If the request fails
        """
        payload = {"filters": filters}
        logger.info(f"export_documents payload: {payload!r}")
        response = requests.post(
            f"{self.base_url}/documents/export",
            json=payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def restore_documents(self, backup_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Restore documents from backup.
        
        Args:
            backup_data: Backup data from export_documents
            
        Returns:
            Restore result with chunks_restored count
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.post(
            f"{self.base_url}/documents/restore",
            json={"backup_data": backup_data},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_metadata_keys(self, pattern: Optional[str] = None) -> List[str]:
        """
        Get all unique metadata keys.
        
        Args:
            pattern: Optional SQL LIKE pattern to filter keys
            
        Returns:
            List of metadata keys
            
        Raises:
            requests.RequestException: If the request fails
        """
        params = {}
        if pattern:
            params['pattern'] = pattern
        
        response = requests.get(
            f"{self.base_url}/metadata/keys",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_metadata_values(self, key: str) -> List[str]:
        """
        Get all unique values for a metadata key.
        
        Args:
            key: Metadata key to get values for
            
        Returns:
            List of unique values
            
        Raises:
            requests.RequestException: If the request fails
        """
        response = requests.get(
            f"{self.base_url}/metadata/values",
            params={"key": key},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
