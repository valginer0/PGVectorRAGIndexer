from typing import Dict, Any, List, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class WatchedFoldersClient:
    """Domain client for watched folders and virtual roots management."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    # ------------------------------------------------------------------
    # Watched Folders (#6)
    # ------------------------------------------------------------------

    def list_watched_folders(self, enabled_only: bool = False) -> Dict[str, Any]:
        """List watched folders."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/watched-folders",
            params={"enabled_only": enabled_only}
        )
        return response.json()

    def add_watched_folder(
        self,
        folder_path: str,
        schedule_cron: str = "0 */6 * * *",
        client_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Add or update a watched folder."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/watched-folders",
            json={
                "folder_path": folder_path,
                "schedule_cron": schedule_cron,
                "client_id": client_id,
                "enabled": enabled,
            }
        )
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
        response = self._base.request(
            "PUT",
            f"{self._base.api_base}/watched-folders/{folder_id}",
            json=body
        )
        return response.json()

    def remove_watched_folder(self, folder_id: str) -> Dict[str, Any]:
        """Remove a watched folder."""
        response = self._base.request(
            "DELETE",
            f"{self._base.api_base}/watched-folders/{folder_id}"
        )
        return response.json()

    def scan_watched_folder(
        self, folder_id: str, client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Trigger an immediate scan of a watched folder."""
        body: Dict[str, Any] = {}
        if client_id:
            body["client_id"] = client_id
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/watched-folders/{folder_id}/scan",
            json=body
        )
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
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/virtual-roots",
            params=params
        )
        return response.json()

    def list_virtual_root_names(self) -> Dict[str, Any]:
        """List distinct virtual root names."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/virtual-roots/names"
        )
        return response.json()

    def get_virtual_root_mappings(self, name: str) -> Dict[str, Any]:
        """Get all client mappings for a virtual root name."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/virtual-roots/{name}/mappings"
        )
        return response.json()

    def add_virtual_root(
        self, name: str, client_id: str, local_path: str
    ) -> Dict[str, Any]:
        """Add or update a virtual root mapping."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/virtual-roots",
            json={"name": name, "client_id": client_id, "local_path": local_path}
        )
        return response.json()

    def remove_virtual_root(self, root_id: str) -> Dict[str, Any]:
        """Remove a virtual root by ID."""
        response = self._base.request(
            "DELETE",
            f"{self._base.api_base}/virtual-roots/{root_id}"
        )
        return response.json()

    def resolve_virtual_path(
        self, virtual_path: str, client_id: str
    ) -> Dict[str, Any]:
        """Resolve a virtual path to a local path."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/virtual-roots/resolve",
            json={"virtual_path": virtual_path, "client_id": client_id}
        )
        return response.json()
