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
        sort_dir: str = "desc",
        source_prefix: str | None = None,
    ) -> Dict[str, Any]:
        """Retrieve documents with pagination metadata."""
        params = {
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }
        if source_prefix:
            params["source_prefix"] = source_prefix

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

    # ------------------------------------------------------------------
    # Client Identity (#8)
    # ------------------------------------------------------------------

    def register_client(
        self,
        client_id: str,
        display_name: str,
        os_type: str,
        app_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register or update a client with the server.

        Returns:
            Dict with client info including last_seen_at.
        """
        response = requests.post(
            f"{self.api_base}/clients/register",
            json={
                "client_id": client_id,
                "display_name": display_name,
                "os_type": os_type,
                "app_version": app_version,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def client_heartbeat(
        self, client_id: str, app_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a heartbeat to update last_seen_at.

        Returns:
            Dict with {"ok": True/False}.
        """
        response = requests.post(
            f"{self.api_base}/clients/heartbeat",
            json={"client_id": client_id, "app_version": app_version},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_clients(self) -> Dict[str, Any]:
        """List all registered clients.

        Returns:
            Dict with 'clients' list and 'count'.
        """
        response = requests.get(
            f"{self.api_base}/clients",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Watched Folders (#6)
    # ------------------------------------------------------------------

    def list_watched_folders(self, enabled_only: bool = False) -> Dict[str, Any]:
        """List watched folders."""
        response = requests.get(
            f"{self.api_base}/watched-folders",
            params={"enabled_only": enabled_only},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def add_watched_folder(
        self,
        folder_path: str,
        schedule_cron: str = "0 */6 * * *",
        client_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Add or update a watched folder."""
        response = requests.post(
            f"{self.api_base}/watched-folders",
            json={
                "folder_path": folder_path,
                "schedule_cron": schedule_cron,
                "client_id": client_id,
                "enabled": enabled,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def update_watched_folder(
        self,
        folder_id: str,
        enabled: Optional[bool] = None,
        schedule_cron: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a watched folder's settings."""
        body: Dict[str, Any] = {}
        if enabled is not None:
            body["enabled"] = enabled
        if schedule_cron is not None:
            body["schedule_cron"] = schedule_cron
        response = requests.put(
            f"{self.api_base}/watched-folders/{folder_id}",
            json=body,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def remove_watched_folder(self, folder_id: str) -> Dict[str, Any]:
        """Remove a watched folder."""
        response = requests.delete(
            f"{self.api_base}/watched-folders/{folder_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def scan_watched_folder(
        self, folder_id: str, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Trigger an immediate scan of a watched folder."""
        body: Dict[str, Any] = {}
        if client_id:
            body["client_id"] = client_id
        response = requests.post(
            f"{self.api_base}/watched-folders/{folder_id}/scan",
            json=body,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Virtual Roots (#9)
    # ------------------------------------------------------------------

    def list_virtual_roots(
        self, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """List virtual roots, optionally filtered by client_id."""
        params: Dict[str, Any] = {}
        if client_id:
            params["client_id"] = client_id
        response = requests.get(
            f"{self.api_base}/virtual-roots",
            params=params,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_virtual_root_names(self) -> Dict[str, Any]:
        """List distinct virtual root names."""
        response = requests.get(
            f"{self.api_base}/virtual-roots/names",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_virtual_root_mappings(self, name: str) -> Dict[str, Any]:
        """Get all client mappings for a virtual root name."""
        response = requests.get(
            f"{self.api_base}/virtual-roots/{name}/mappings",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def add_virtual_root(
        self, name: str, client_id: str, local_path: str
    ) -> Dict[str, Any]:
        """Add or update a virtual root mapping."""
        response = requests.post(
            f"{self.api_base}/virtual-roots",
            json={"name": name, "client_id": client_id, "local_path": local_path},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def remove_virtual_root(self, root_id: str) -> Dict[str, Any]:
        """Remove a virtual root by ID."""
        response = requests.delete(
            f"{self.api_base}/virtual-roots/{root_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def resolve_virtual_path(
        self, virtual_path: str, client_id: str
    ) -> Dict[str, Any]:
        """Resolve a virtual path to a local path."""
        response = requests.post(
            f"{self.api_base}/virtual-roots/resolve",
            json={"virtual_path": virtual_path, "client_id": client_id},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Activity Log (#10)
    # ------------------------------------------------------------------

    def get_activity_log(
        self,
        limit: int = 50,
        offset: int = 0,
        client_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query recent activity log entries."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if client_id:
            params["client_id"] = client_id
        if action:
            params["action"] = action
        response = requests.get(
            f"{self.api_base}/activity",
            params=params,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post_activity(
        self,
        action: str,
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an activity log entry."""
        response = requests.post(
            f"{self.api_base}/activity",
            json={
                "action": action,
                "client_id": client_id,
                "user_id": user_id,
                "details": details,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_activity_action_types(self) -> Dict[str, Any]:
        """Get distinct action types in the activity log."""
        response = requests.get(
            f"{self.api_base}/activity/actions",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def export_activity_csv(
        self,
        client_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> str:
        """Export activity log as CSV string."""
        params: Dict[str, Any] = {}
        if client_id:
            params["client_id"] = client_id
        if action:
            params["action"] = action
        response = requests.get(
            f"{self.api_base}/activity/export",
            params=params,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def apply_activity_retention(self, days: int) -> Dict[str, Any]:
        """Apply retention policy — delete entries older than N days."""
        response = requests.post(
            f"{self.api_base}/activity/retention",
            json={"days": days},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Document Tree (#7)
    # ------------------------------------------------------------------

    def get_document_tree(
        self,
        parent_path: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get one level of the document tree under parent_path."""
        response = requests.get(
            f"{self.api_base}/documents/tree",
            params={"parent_path": parent_path, "limit": limit, "offset": offset},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_document_tree_stats(self) -> Dict[str, Any]:
        """Get overall document tree statistics."""
        response = requests.get(
            f"{self.api_base}/documents/tree/stats",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def search_document_tree(
        self, query: str, limit: int = 50
    ) -> Dict[str, Any]:
        """Search for documents matching a path pattern."""
        response = requests.get(
            f"{self.api_base}/documents/tree/search",
            params={"q": query, "limit": limit},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Document Locks (#3 Multi-User, Phase 1)
    # ------------------------------------------------------------------

    def acquire_document_lock(
        self,
        source_uri: str,
        client_id: str,
        ttl_minutes: int = 10,
        lock_reason: str = "indexing",
    ) -> Dict[str, Any]:
        """Acquire a lock on a document for indexing."""
        response = requests.post(
            f"{self.api_base}/documents/locks/acquire",
            json={
                "source_uri": source_uri,
                "client_id": client_id,
                "ttl_minutes": ttl_minutes,
                "lock_reason": lock_reason,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def release_document_lock(
        self, source_uri: str, client_id: str
    ) -> Dict[str, Any]:
        """Release a lock on a document."""
        response = requests.post(
            f"{self.api_base}/documents/locks/release",
            json={"source_uri": source_uri, "client_id": client_id},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def force_release_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Force-release a lock regardless of holder (admin)."""
        response = requests.post(
            f"{self.api_base}/documents/locks/force-release",
            json={"source_uri": source_uri},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_document_locks(
        self, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """List all active document locks."""
        params: Dict[str, Any] = {}
        if client_id:
            params["client_id"] = client_id
        response = requests.get(
            f"{self.api_base}/documents/locks",
            params=params,
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def check_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Check if a specific document is locked."""
        response = requests.get(
            f"{self.api_base}/documents/locks/check",
            params={"source_uri": source_uri},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def cleanup_expired_locks(self) -> Dict[str, Any]:
        """Remove all expired locks."""
        response = requests.post(
            f"{self.api_base}/documents/locks/cleanup",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # User Management (#16 Enterprise Foundations)
    # ------------------------------------------------------------------

    def list_users(self, role: str = None, active_only: bool = True) -> dict:
        """List all users, optionally filtered by role."""
        params = {"active_only": active_only}
        if role:
            params["role"] = role
        response = requests.get(
            f"{self.api_base}/users",
            headers=self._headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_user(self, user_id: str) -> dict:
        """Get a user by ID."""
        response = requests.get(
            f"{self.api_base}/users/{user_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def create_user(
        self,
        *,
        email: str = None,
        display_name: str = None,
        role: str = "user",
        api_key_id: int = None,
        client_id: str = None,
    ) -> dict:
        """Create a new user (admin only)."""
        payload = {"role": role}
        if email:
            payload["email"] = email
        if display_name:
            payload["display_name"] = display_name
        if api_key_id is not None:
            payload["api_key_id"] = api_key_id
        if client_id:
            payload["client_id"] = client_id
        response = requests.post(
            f"{self.api_base}/users",
            headers=self._headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def update_user(self, user_id: str, **kwargs) -> dict:
        """Update a user (admin only). Pass email, display_name, role, is_active."""
        response = requests.put(
            f"{self.api_base}/users/{user_id}",
            headers=self._headers,
            json=kwargs,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def delete_user(self, user_id: str) -> dict:
        """Delete a user (admin only)."""
        response = requests.delete(
            f"{self.api_base}/users/{user_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def change_user_role(self, user_id: str, role: str) -> dict:
        """Change a user's role (admin only)."""
        response = requests.post(
            f"{self.api_base}/users/{user_id}/role",
            headers=self._headers,
            json={"role": role},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Document Visibility (#3 Multi-User Support Phase 2)
    # ------------------------------------------------------------------

    def get_document_visibility(self, document_id: str) -> dict:
        """Get visibility info for a document."""
        response = requests.get(
            f"{self.api_base}/documents/{document_id}/visibility",
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def set_document_visibility(
        self, document_id: str, *, visibility: str = None, owner_id: str = None
    ) -> dict:
        """Set visibility and/or owner for a document."""
        payload = {}
        if visibility:
            payload["visibility"] = visibility
        if owner_id:
            payload["owner_id"] = owner_id
        response = requests.put(
            f"{self.api_base}/documents/{document_id}/visibility",
            headers=self._headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def transfer_document_ownership(self, document_id: str, new_owner_id: str) -> dict:
        """Transfer document ownership to another user (admin only)."""
        response = requests.post(
            f"{self.api_base}/documents/{document_id}/transfer",
            headers=self._headers,
            json={"new_owner_id": new_owner_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_user_documents(
        self, user_id: str, visibility: str = None, limit: int = 100, offset: int = 0
    ) -> dict:
        """List documents owned by a specific user."""
        params = {"limit": limit, "offset": offset}
        if visibility:
            params["visibility"] = visibility
        response = requests.get(
            f"{self.api_base}/users/{user_id}/documents",
            headers=self._headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def bulk_set_document_visibility(self, document_ids: list, visibility: str) -> dict:
        """Set visibility for multiple documents at once (admin only)."""
        response = requests.post(
            f"{self.api_base}/documents/bulk-visibility",
            headers=self._headers,
            json={"document_ids": document_ids, "visibility": visibility},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
