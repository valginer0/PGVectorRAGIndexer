"""
REST API client for communicating with the backend.
This module now serves as a 100% backward-compatible Façade over the `api_client_core` packages.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from desktop_app.utils.hashing import calculate_source_id
from desktop_app.utils.api_client_core.base_client import BaseAPIClient
from desktop_app.utils.api_client_core.system_client import SystemClient
from desktop_app.utils.api_client_core.document_client import DocumentClient
from desktop_app.utils.api_client_core.search_client import SearchClient
from desktop_app.utils.api_client_core.metadata_client import MetadataClient
from desktop_app.utils.api_client_core.indexing_client import IndexingClient
from desktop_app.utils.api_client_core.user_client import UserClient
from desktop_app.utils.api_client_core.activity_client import ActivityClient
from desktop_app.utils.api_client_core.watched_folders_client import WatchedFoldersClient
from desktop_app.utils.api_client_core.identity_client import IdentityClient
from desktop_app.utils.api_client_core.maintenance_client import MaintenanceClient
from desktop_app.utils.errors import APIError, APIConnectionError, APIAuthenticationError
from version import __version__ as CLIENT_VERSION

logger = logging.getLogger(__name__)


class CapabilityStatus(Enum):
    """Result of probing a server endpoint for capability detection."""
    AVAILABLE = "available"          # 200 OK
    UNAUTHORIZED = "unauthorized"    # 401/403
    NOT_SUPPORTED = "not_supported"  # 404/405
    UNREACHABLE = "unreachable"      # ConnectionError/Timeout
    UNKNOWN = "unknown"              # Not yet probed


@dataclass
class ProbeResult:
    """Result of a lightweight endpoint probe."""
    status: CapabilityStatus
    body: Optional[dict] = None           # Response JSON on 200, None otherwise
    error_message: Optional[str] = None   # Error detail on 500/error
    status_code: Optional[int] = None     # Raw HTTP status, None on connection error
    error_code: Optional[str] = None      # Specific ErrorCode identifier (e.g. LIC_3006)


# Legacy exceptions kept here to allow `except APIClient.Error:` patterns if any exist,
# but normally these should import from `errors.py`.
# For Phase D migration, we rely on the concrete BaseAPIClient handling error mappings.


class APIClient:
    """
    Façade client for interacting with the PGVectorRAGIndexer REST API.
    All underlying HTTP and state management is routed through `BaseAPIClient`.
    Domain methods currently reside here but will systematically migrate to sub-modules.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None, timeout: int = 7200):
        """
        Initialize API client Façade.
        
        Args:
            base_url: Base URL of the API
            api_key: Optional API key for authenticated access (remote mode)
            timeout: Default request timeout in seconds (default: 7200 for large OCR files)
        """
        # Centralized HTTP configuration and state management
        self._base = BaseAPIClient(base_url, api_key, timeout)
        
        # Domain Client Instantiations (Batch 1, 2, 3)
        self._system = SystemClient(self._base)
        self._document = DocumentClient(self._base)
        self._search = SearchClient(self._base)
        self._metadata = MetadataClient(self._base)
        self._indexing = IndexingClient(self._base)
        self._user = UserClient(self._base)
        self._activity = ActivityClient(self._base)
        self._watched_folders = WatchedFoldersClient(self._base)
        self._identity = IdentityClient(self._base)
        self._maintenance = MaintenanceClient(self._base)

        # Deprecated: Server version is now managed by SystemClient but kept here temporarily
        # if any legacy callers accessed `api_client._server_version` directly.
        self._server_version: Optional[str] = None
        
    @property
    def base_url(self) -> str:
        return self._base.base_url
        
    @base_url.setter
    def base_url(self, value: str):
        # BaseAPIClient.base_url setter automatically normalizes via rstrip('/') 
        # and re-derives `api_base`.
        self._base.base_url = value
        
    @property
    def api_base(self) -> str:
        return self._base.api_base

    @api_base.setter
    def api_base(self, value: str):
        # Restored specifically to guarantee strict runtime compatibility 
        # if legacy code overrides api_base directly without updating base_url.
        self._base.api_base = value.rstrip('/') if value else value # type: ignore
        
    @property
    def _api_key(self) -> Optional[str]:
        return self._base.api_key
        
    @_api_key.setter
    def _api_key(self, value: Optional[str]):
        # BaseAPIClient.api_key enforces synchronization invariant: 
        # immediately patches X-API-Key into self._base._session.headers.
        self._base.api_key = value

    @property
    def timeout(self) -> int:
        return self._base._timeout
        
    @timeout.setter
    def timeout(self, value: int):
        self._base._timeout = value

    def close(self):
        """Releases the underlying session connection pool."""
        self._base.close()

    def get_health(self) -> Dict[str, Any]:
        """Get the full health status of the API."""
        return self._system.get_health()

    def is_api_available(self) -> bool:
        """Check if the API is available (responding 200)."""
        return self._system.is_api_available()

    def check_version_compatibility(self) -> Tuple[bool, str]:
        """Check if this client version is compatible with the server."""
        compatible, msg = self._system.check_version_compatibility()
        self._server_version = self._system._server_version  # Sync deprecated legacy property
        return compatible, msg

    def check_document_exists(self, source_uri: str) -> bool:
        """Check if a document with the given source URI already exists."""
        return self._document.check_document_exists(source_uri)

    def get_document_metadata(self, source_uri: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a document by source URI."""
        return self._document.get_document_metadata(source_uri)
    
    def upload_document(
        self,
        file_path: Path,
        custom_source_uri: Optional[str] = None,
        force_reindex: bool = False,
        document_type: Optional[str] = None,
        ocr_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload and index a document."""
        return self._document.upload_document(
            file_path, custom_source_uri, force_reindex, document_type, ocr_mode
        )
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.5,
        metric: str = "cosine",
        document_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search for documents."""
        return self._search.search(
            query=query,
            top_k=top_k,
            min_score=min_score,
            metric=metric,
            document_type=document_type,
            filters=filters
        )
    
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
        return self._document.list_documents(
            limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, source_prefix=source_prefix
        )
    
    def get_document(self, document_id: str) -> Dict[str, Any]:
        """Get a specific document by ID."""
        return self._document.get_document(document_id)
    
    def delete_document(self, document_id: str) -> Dict[str, Any]:
        """Delete a document."""
        return self._document.delete_document(document_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        return self._system.get_statistics()
    
    def bulk_delete_preview(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Preview what documents would be deleted with given filters."""
        return self._document.bulk_delete_preview(filters)
    
    def bulk_delete(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Actually delete documents matching filters."""
        return self._document.bulk_delete(filters)
    
    def export_documents(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Export documents matching filters as backup."""
        return self._document.export_documents(filters)
    
    def restore_documents(self, backup_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Restore documents from backup."""
        return self._document.restore_documents(backup_data)
    
    def get_metadata_keys(self, pattern: Optional[str] = None) -> List[str]:
        """Get all unique metadata keys."""
        return self._metadata.get_metadata_keys(pattern=pattern)
    
    def get_metadata_values(self, key: str) -> List[str]:
        """Get all unique values for a metadata key."""
        return self._metadata.get_metadata_values(key=key)

    # ------------------------------------------------------------------
    # Health Dashboard (#4)
    # ------------------------------------------------------------------

    def get_indexing_runs(self, limit: int = 20) -> Dict[str, Any]:
        """Get recent indexing runs."""
        return self._indexing.get_indexing_runs(limit=limit)

    def get_indexing_summary(self) -> Dict[str, Any]:
        """Get aggregate indexing run statistics."""
        return self._indexing.get_indexing_summary()

    def get_indexing_run_detail(self, run_id: str) -> Dict[str, Any]:
        """Get details of a single indexing run."""
        return self._indexing.get_indexing_run_detail(run_id=run_id)

    # ------------------------------------------------------------------
    # Current Identity
    # ------------------------------------------------------------------

    def get_me(self) -> dict:
        """Get the identity and permissions of the current API key holder."""
        return self._identity.get_me()

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
        """Register or update a client with the server."""
        return self._identity.register_client(
            client_id=client_id,
            display_name=display_name,
            os_type=os_type,
            app_version=app_version
        )

    def client_heartbeat(
        self, client_id: str, app_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a heartbeat to update last_seen_at."""
        return self._identity.client_heartbeat(client_id=client_id, app_version=app_version)

    def list_clients(self) -> Dict[str, Any]:
        """List all registered clients."""
        return self._identity.list_clients()

    # ------------------------------------------------------------------
    # Watched Folders (#6)
    # ------------------------------------------------------------------

    def list_watched_folders(self, enabled_only: bool = False) -> Dict[str, Any]:
        """List watched folders."""
        return self._watched_folders.list_watched_folders(enabled_only=enabled_only)

    def add_watched_folder(
        self,
        folder_path: str,
        schedule_cron: str = "0 */6 * * *",
        client_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Add or update a watched folder."""
        return self._watched_folders.add_watched_folder(
            folder_path=folder_path,
            schedule_cron=schedule_cron,
            client_id=client_id,
            enabled=enabled
        )

    def update_watched_folder(
        self,
        folder_id: str,
        enabled: Optional[bool] = None,
        schedule_cron: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a watched folder's settings."""
        return self._watched_folders.update_watched_folder(
            folder_id=folder_id,
            enabled=enabled,
            schedule_cron=schedule_cron
        )

    def remove_watched_folder(self, folder_id: str) -> Dict[str, Any]:
        """Remove a watched folder."""
        return self._watched_folders.remove_watched_folder(folder_id=folder_id)

    def scan_watched_folder(
        self, folder_id: str, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Trigger an immediate scan of a watched folder."""
        return self._watched_folders.scan_watched_folder(folder_id=folder_id, client_id=client_id)

    # ------------------------------------------------------------------
    # Virtual Roots (#9)
    # ------------------------------------------------------------------

    def list_virtual_roots(
        self, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """List virtual roots, optionally filtered by client_id."""
        return self._watched_folders.list_virtual_roots(client_id=client_id)

    def list_virtual_root_names(self) -> Dict[str, Any]:
        """List distinct virtual root names."""
        return self._watched_folders.list_virtual_root_names()

    def get_virtual_root_mappings(self, name: str) -> Dict[str, Any]:
        """Get all client mappings for a virtual root name."""
        return self._watched_folders.get_virtual_root_mappings(name=name)

    def add_virtual_root(
        self, name: str, client_id: str, local_path: str
    ) -> Dict[str, Any]:
        """Add or update a virtual root mapping."""
        return self._watched_folders.add_virtual_root(name=name, client_id=client_id, local_path=local_path)

    def remove_virtual_root(self, root_id: str) -> Dict[str, Any]:
        """Remove a virtual root by ID."""
        return self._watched_folders.remove_virtual_root(root_id=root_id)

    def resolve_virtual_path(
        self, virtual_path: str, client_id: str
    ) -> Dict[str, Any]:
        """Resolve a virtual path to a local path."""
        return self._watched_folders.resolve_virtual_path(virtual_path=virtual_path, client_id=client_id)

    # ------------------------------------------------------------------
    # Licensing
    # ------------------------------------------------------------------

    def get_license_info(self) -> Dict[str, Any]:
        """Get license information from the server."""
        return self._system.get_license_info()

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
        return self._activity.get_activity_log(limit=limit, offset=offset, client_id=client_id, action=action)

    def post_activity(
        self,
        action: str,
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an activity log entry."""
        return self._activity.post_activity(action=action, client_id=client_id, user_id=user_id, details=details)

    def get_activity_action_types(self) -> Dict[str, Any]:
        """Get distinct action types in the activity log."""
        return self._activity.get_activity_action_types()

    def export_activity_csv(
        self,
        client_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> str:
        """Export activity log as CSV string."""
        return self._activity.export_activity_csv(client_id=client_id, action=action)

    def apply_activity_retention(self, days: int) -> Dict[str, Any]:
        """Apply retention policy — delete entries older than N days."""
        return self._activity.apply_activity_retention(days=days)

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
        return self._document.get_document_tree(parent_path, limit, offset)

    def get_document_tree_stats(self) -> Dict[str, Any]:
        """Get overall document tree statistics."""
        return self._document.get_document_tree_stats()

    def search_document_tree(
        self, query: str, limit: int = 50
    ) -> Dict[str, Any]:
        """Search for documents matching a path pattern."""
        return self._document.search_document_tree(query, limit)

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
        return self._document.acquire_document_lock(source_uri, client_id, ttl_minutes, lock_reason)

    def release_document_lock(
        self, source_uri: str, client_id: str
    ) -> Dict[str, Any]:
        """Release a lock on a document."""
        return self._document.release_document_lock(source_uri, client_id)

    def force_release_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Force-release a lock regardless of holder (admin)."""
        return self._document.force_release_document_lock(source_uri)

    def list_document_locks(
        self, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """List all active document locks."""
        return self._document.list_document_locks(client_id)

    def check_document_lock(self, source_uri: str) -> Dict[str, Any]:
        """Check if a specific document is locked."""
        return self._document.check_document_lock(source_uri)

    def cleanup_expired_locks(self) -> Dict[str, Any]:
        """Remove all expired locks."""
        return self._document.cleanup_expired_locks()

    # ------------------------------------------------------------------
    # User Management (#16 Enterprise Foundations)
    # ------------------------------------------------------------------

    def list_users(self, role: str = None, active_only: bool = True) -> dict:
        """List all users, optionally filtered by role."""
        return self._user.list_users(role=role, active_only=active_only)

    def get_user(self, user_id: str) -> dict:
        """Get a user by ID."""
        return self._user.get_user(user_id=user_id)

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
        return self._user.create_user(
            email=email,
            display_name=display_name,
            role=role,
            api_key_id=api_key_id,
            client_id=client_id,
        )

    def update_user(self, user_id: str, **kwargs) -> dict:
        """Update a user (admin only). Pass email, display_name, role, is_active."""
        return self._user.update_user(user_id, **kwargs)

    def delete_user(self, user_id: str) -> dict:
        """Delete a user (admin only)."""
        return self._user.delete_user(user_id=user_id)

    def change_user_role(self, user_id: str, role: str) -> dict:
        """Change a user's role (admin only)."""
        return self._user.change_user_role(user_id=user_id, role=role)

    # ------------------------------------------------------------------
    # Document Visibility (#3 Multi-User Support Phase 2)
    # ------------------------------------------------------------------

    def get_document_visibility(self, document_id: str) -> dict:
        """Get visibility info for a document."""
        return self._document.get_document_visibility(document_id=document_id)

    def set_document_visibility(
        self, document_id: str, *, visibility: str = None, owner_id: str = None
    ) -> dict:
        """Set visibility and/or owner for a document."""
        return self._document.set_document_visibility(document_id, visibility=visibility, owner_id=owner_id)

    def transfer_document_ownership(self, document_id: str, new_owner_id: str) -> dict:
        """Transfer document ownership to another user (admin only)."""
        return self._document.transfer_document_ownership(document_id, new_owner_id)

    def list_user_documents(
        self, user_id: str, visibility: str = None, limit: int = 100, offset: int = 0
    ) -> dict:
        """List documents owned by a specific user."""
        return self._user.list_user_documents(user_id=user_id, visibility=visibility, limit=limit, offset=offset)

    def bulk_set_document_visibility(self, document_ids: list, visibility: str) -> dict:
        """Set visibility for multiple documents at once (admin only)."""
        return self._document.bulk_set_document_visibility(document_ids, visibility)

    # ------------------------------------------------------------------
    # Roles & Permissions
    # ------------------------------------------------------------------

    def list_roles(self) -> dict:
        """List all roles with their permissions."""
        return self._user.list_roles()

    def get_role(self, name: str) -> dict:
        """Get a single role by name."""
        return self._user.get_role(name)

    def list_permissions(self) -> dict:
        """List all available permissions."""
        return self._user.list_permissions()

    # ------------------------------------------------------------------
    # Maintenance (Retention)
    # ------------------------------------------------------------------

    def get_retention_policy(self) -> dict:
        """Get the effective retention policy defaults."""
        return self._maintenance.get_retention_policy()

    def get_retention_status(self) -> dict:
        """Get retention execution status."""
        return self._maintenance.get_retention_status()

    def run_retention(self, **kwargs) -> dict:
        """Run a one-off retention cycle."""
        return self._maintenance.run_retention(**kwargs)

    def export_compliance_report(self) -> bytes:
        """Download the compliance report ZIP file."""
        return self._maintenance.export_compliance_report()

    # ------------------------------------------------------------------
    # API Key Management
    # ------------------------------------------------------------------

    def list_keys(self) -> dict:
        """List all API keys."""
        return self._identity.list_keys()

    def create_key(self, name: str) -> dict:
        """Create a new API key."""
        return self._identity.create_key(name)

    def revoke_key(self, key_id: int) -> dict:
        """Revoke an API key."""
        return self._identity.revoke_key(key_id)

    def rotate_key(self, key_id: int) -> dict:
        """Rotate an API key (24h grace period)."""
        return self._identity.rotate_key(key_id)

    # ------------------------------------------------------------------
    # Endpoint Probing (Capability Detection)
    # ------------------------------------------------------------------

    def probe_endpoint(self, path: str, timeout: int = 3) -> ProbeResult:
        """Lightweight GET probe for capability detection.

        Designed for JSON API endpoints only. Returns a ProbeResult with
        status, body (on 200), and error_message (on 500 or error).

        NOTE: Uses self._base._session directly rather than BaseAPIClient.request()
        because probes need different semantics: short timeout, no exception raising,
        and status-code-to-enum mapping. If cross-cutting concerns are added to
        BaseAPIClient.request() later, verify whether probes should also adopt them.
        """
        import requests as _requests

        url = f"{self._base.base_url}{path}"
        try:
            response = self._base._session.request("GET", url, timeout=timeout)
            code = response.status_code

            if code == 200:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                return ProbeResult(
                    status=CapabilityStatus.AVAILABLE,
                    body=body,
                    status_code=code,
                )
            elif code in (401, 403, 404, 405) or code >= 500:
                err_msg = None
                err_code = None
                try:
                    err_data = response.json()
                    if isinstance(err_data, dict):
                        if "error_code" in err_data:
                            # Flattened format (custom exception handler)
                            err_code = err_data.get("error_code")
                            err_msg = err_data.get("message", str(err_data))
                        elif "detail" in err_data:
                            # Standard FastAPI format
                            detail = err_data["detail"]
                            if isinstance(detail, dict):
                                err_code = detail.get("error_code")
                                err_msg = detail.get("message", str(detail))
                            else:
                                err_msg = str(detail)
                        else:
                            err_msg = str(err_data)
                except (ValueError, AttributeError):
                    err_msg = response.text[:200] if response.text else f"HTTP {code}"

                if code in (401, 403):
                    return ProbeResult(
                        status=CapabilityStatus.UNAUTHORIZED,
                        status_code=code,
                        error_message=err_msg,
                        error_code=err_code,
                    )
                elif code in (404, 405):
                    return ProbeResult(
                        status=CapabilityStatus.NOT_SUPPORTED,
                        status_code=code,
                        error_message=err_msg,
                        error_code=err_code,
                    )
                else:
                    return ProbeResult(
                        status=CapabilityStatus.AVAILABLE,
                        error_message=err_msg,
                        status_code=code,
                        error_code=err_code,
                    )
        except (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout):
            return ProbeResult(status=CapabilityStatus.UNREACHABLE)
        except Exception as e:
            return ProbeResult(
                status=CapabilityStatus.UNREACHABLE,
                error_message=str(e),
            )
