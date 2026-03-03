import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from desktop_app.utils.hashing import calculate_source_id
from desktop_app.utils.api_client_core.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class DocumentClient:
    """Domain client for document CRUD, tree management, and locks."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    def check_document_exists(self, source_uri: str) -> bool:
        """Check if a document with the given source URI already exists."""
        return self.get_document_metadata(source_uri) is not None

    def get_document_metadata(self, source_uri: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a document by source URI."""
        try:
            document_id = calculate_source_id(source_uri)
            # `request` throws APIError on 404, we must catch it specifically
            return self.get_document(document_id)
        except Exception as e:
            # Safely check the underling HTTP status instead of string matching
            if getattr(e, "status_code", None) == 404:
                return None
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
        """Upload and index a document."""
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
            
            response = self._base.request(
                "POST",
                f"{self._base.api_base}/upload-and-index",
                files=files,
                data=data
            )
            return response.json()
    
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

        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents",
            params=params
        )
        data = response.json()

        if isinstance(data, list):
            return {
                "items": data,
                "total": len(data),
                "limit": limit,
                "offset": offset,
                "sort": {"by": sort_by, "direction": sort_dir},
                "_total_estimated": True,
            }

        if isinstance(data, dict):
            if "items" in data:
                normalized = dict(data)
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

        from desktop_app.utils.errors import APIError
        raise APIError("Unexpected response structure from /documents endpoint")
    
    def get_document(self, document_id: str) -> Dict[str, Any]:
        """Get a specific document by ID."""
        response = self._base.request("GET", f"{self._base.api_base}/documents/{document_id}")
        return response.json()
    
    def delete_document(self, document_id: str) -> Dict[str, Any]:
        """Delete a document."""
        logger.info(f"Deleting document: {document_id}")
        response = self._base.request("DELETE", f"{self._base.api_base}/documents/{document_id}")
        return response.json()
    
    def bulk_delete_preview(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Preview what documents would be deleted with given filters."""
        payload = {"filters": filters, "preview": True}
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/bulk-delete",
            json=payload
        )
        return response.json()
    
    def bulk_delete(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Actually delete documents matching filters."""
        payload = {"filters": filters, "preview": False}
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/bulk-delete",
            json=payload
        )
        return response.json()
    
    def export_documents(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Export documents matching filters as backup."""
        payload = {"filters": filters}
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/export",
            json=payload
        )
        return response.json()
    
    def restore_documents(self, backup_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Restore documents from backup."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/restore",
            json={"backup_data": backup_data}
        )
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
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/tree",
            params={"parent_path": parent_path, "limit": limit, "offset": offset}
        )
        return response.json()

    def get_document_tree_stats(self) -> Dict[str, Any]:
        """Get overall document tree statistics."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/tree/stats"
        )
        return response.json()

    def search_document_tree(
        self, query: str, limit: int = 50
    ) -> Dict[str, Any]:
        """Search for documents matching a path pattern."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/tree/search",
            params={"q": query, "limit": limit}
        )
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
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/locks/acquire",
            json={
                "source_uri": source_uri,
                "client_id": client_id,
                "ttl_minutes": ttl_minutes,
                "lock_reason": lock_reason,
            }
        )
        return response.json()

    def release_document_lock(
        self, source_uri: str, client_id: str
    ) -> Dict[str, Any]:
        """Release a lock on a document."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/locks/release",
            json={"source_uri": source_uri, "client_id": client_id}
        )
        return response.json()

    def force_release_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Force-release a lock regardless of holder (admin)."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/locks/force-release",
            json={"source_uri": source_uri}
        )
        return response.json()

    def list_document_locks(
        self, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """List all active document locks."""
        params: Dict[str, Any] = {}
        if client_id:
            params["client_id"] = client_id
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/locks",
            params=params
        )
        return response.json()

    def check_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Check if a specific document is locked."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/locks/check",
            params={"source_uri": source_uri}
        )
        return response.json()

    def cleanup_expired_locks(self) -> Dict[str, Any]:
        """Remove all expired locks."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/locks/cleanup"
        )
        return response.json()

    # ------------------------------------------------------------------
    # Document Visibility (#3 Multi-User Support Phase 2)
    # ------------------------------------------------------------------

    def get_document_visibility(self, document_id: str) -> dict:
        """Get visibility info for a document."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/documents/{document_id}/visibility"
        )
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
        response = self._base.request(
            "PUT",
            f"{self._base.api_base}/documents/{document_id}/visibility",
            json=payload
        )
        return response.json()

    def transfer_document_ownership(self, document_id: str, new_owner_id: str) -> dict:
        """Transfer document ownership to another user (admin only)."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/{document_id}/transfer",
            json={"new_owner_id": new_owner_id}
        )
        return response.json()

    def bulk_set_document_visibility(self, document_ids: list, visibility: str) -> dict:
        """Set visibility for multiple documents at once (admin only)."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/documents/bulk-visibility",
            json={"document_ids": document_ids, "visibility": visibility}
        )
        return response.json()
