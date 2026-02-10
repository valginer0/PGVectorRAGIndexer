"""
REST API client for communicating with the backend.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

import requests
from desktop_app.utils.hashing import calculate_source_id
from version import __version__ as CLIENT_VERSION

logger = logging.getLogger(__name__)


class APIClient:
    """Client for interacting with the PGVectorRAGIndexer REST API."""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL of the API
            api_key: Optional API key for authenticated access (remote mode)
        """
        self.base_url = base_url.rstrip('/')
        self.api_base = f"{self.base_url}/api/v1"  # Versioned endpoint prefix
        self.timeout = 7200  # 2 hours for very large OCR files (200+ pages)
        self._api_key = api_key
        self._server_version: Optional[str] = None

    @property
    def _headers(self) -> dict:
        """Request headers, including API key if configured."""
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers
    
    def is_api_available(self) -> bool:
        """Check if the API is available."""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                headers=self._headers,
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def check_version_compatibility(self) -> Tuple[bool, str]:
        """Check if this client version is compatible with the server.

        Returns:
            Tuple of (compatible, message).
            compatible is True if versions match, False if mismatch.
            message is empty on success, or a human-readable warning.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/version",
                headers=self._headers,
                timeout=5,
            )
            if response.status_code != 200:
                return True, ""  # Endpoint missing (old server) — assume OK

            data = response.json()
            self._server_version = data.get("server_version", "unknown")
            min_ver = data.get("min_client_version", "0.0.0")
            max_ver = data.get("max_client_version", "99.99.99")

            from packaging.version import Version, InvalidVersion
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
        except requests.RequestException:
            return True, ""  # Can't reach server — don't block

    def check_document_exists(self, source_uri: str) -> bool:
        """
        Check if a document with the given source URI already exists.
        
        Args:
            source_uri: Source URI to check
            
        Returns:
            True if document exists, False otherwise
        """
        return self.get_document_metadata(source_uri) is not None

    def get_document_metadata(self, source_uri: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a document by source URI.
        
        Args:
            source_uri: Source URI to check
            
        Returns:
            Document metadata dict if exists, None otherwise
        """
        try:
            # Calculate deterministic ID locally (O(1))
            document_id = calculate_source_id(source_uri)
            
            # Fetch document details directly
            doc = self.get_document(document_id)
            
            # Return the full document response which includes 'metadata'
            # The API returns dict with keys: document_id, source_uri, chunks_indexed, metadata, etc.
            # But get_document returns the result from /documents/{id}.
            # Let's verify what /documents/{id} returns.
            # It usually returns { "document_id": ..., "metadata": ... }
            return doc
            
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Error checking document status: {e}")
            return None
    
    def upload_document(
        self,
        file_path: Path,
        custom_source_uri: Optional[str] = None,
        force_reindex: bool = False,
        document_type: Optional[str] = None,
        ocr_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload and index a document.
        
        Args:
            file_path: Path to the file to upload
            custom_source_uri: Custom source URI (full path) to preserve
            force_reindex: Whether to force reindexing if document exists
            document_type: Optional document type/category (e.g., 'resume', 'policy', 'report')
            ocr_mode: OCR mode ('auto', 'skip', 'only') - defaults to API config
            
        Returns:
            Response data from the API
            
        Raises:
            requests.RequestException: If the request fails
        """
        logger.info(f"Uploading document: {file_path} (type: {document_type}, ocr: {ocr_mode})")
        
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f)}
            data = {'force_reindex': str(force_reindex).lower()}
            
            if custom_source_uri:
                data['custom_source_uri'] = custom_source_uri
            
            if document_type:
                data['document_type'] = document_type
            
            if ocr_mode:
                data['ocr_mode'] = ocr_mode
            
            response = requests.post(
                f"{self.api_base}/upload-and-index",
                files=files,
                data=data,
                headers=self._headers,
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
            "metric": metric,
            "use_hybrid": True  # Hybrid search with exact-match boost (optimized)
        }
        
        # Add filters if specified
        if filters:
            payload["filters"] = filters
        elif document_type:
            # Backward compatibility
            payload["filters"] = {"type": document_type}
        
        response = requests.post(
            f"{self.api_base}/search",
            json=payload,
            headers=self._headers,
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
            f"{self.api_base}/documents",
            params=params,
            headers=self._headers,
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
            f"{self.api_base}/documents/{document_id}",
            headers=self._headers,
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
            f"{self.api_base}/documents/{document_id}",
            headers=self._headers,
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
            f"{self.api_base}/statistics",
            headers=self._headers,
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
            f"{self.api_base}/documents/bulk-delete",
            json=payload,
            headers=self._headers,
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
            f"{self.api_base}/documents/bulk-delete",
            json=payload,
            headers=self._headers,
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
            f"{self.api_base}/documents/export",
            json=payload,
            headers=self._headers,
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
            f"{self.api_base}/documents/restore",
            json={"backup_data": backup_data},
            headers=self._headers,
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
            f"{self.api_base}/metadata/keys",
            params=params,
            headers=self._headers,
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
            f"{self.api_base}/metadata/values",
            params={"key": key},
            headers=self._headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Health Dashboard (#4)
    # ------------------------------------------------------------------

    def get_indexing_runs(self, limit: int = 20) -> Dict[str, Any]:
        """Get recent indexing runs.

        Args:
            limit: Maximum number of runs to return (1-100).

        Returns:
            Dict with 'runs' list and 'count'.
        """
        response = requests.get(
            f"{self.api_base}/indexing/runs",
            params={"limit": limit},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_indexing_summary(self) -> Dict[str, Any]:
        """Get aggregate indexing run statistics.

        Returns:
            Dict with total_runs, successful, failed, partial,
            total_files_added, total_files_updated, last_run_at.
        """
        response = requests.get(
            f"{self.api_base}/indexing/runs/summary",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_indexing_run_detail(self, run_id: str) -> Dict[str, Any]:
        """Get details of a single indexing run.

        Args:
            run_id: UUID of the run.

        Returns:
            Dict with full run details including errors.
        """
        response = requests.get(
            f"{self.api_base}/indexing/runs/{run_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
