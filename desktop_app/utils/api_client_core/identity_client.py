from typing import Dict, Any, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class IdentityClient:
    """Domain client for client identity and heartbeat management."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    # ------------------------------------------------------------------
    # Current Identity
    # ------------------------------------------------------------------

    def get_me(self) -> Dict[str, Any]:
        """Get the identity and permissions of the current API key holder."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/me",
            timeout=5
        )
        return response.json()

    # ------------------------------------------------------------------
    # Client Identity (#3 Multi-User, Phase 1)
    # ------------------------------------------------------------------

    def register_client(
        self,
        client_id: str,
        display_name: str,
        os_type: str,
        app_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register or update a client with the server."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/clients/register",
            json={
                "client_id": client_id,
                "display_name": display_name,
                "os_type": os_type,
                "app_version": app_version,
            }
        )
        return response.json()

    def client_heartbeat(
        self, client_id: str, app_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a heartbeat to update last_seen_at."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/clients/heartbeat",
            json={"client_id": client_id, "app_version": app_version}
        )
        return response.json()

    def list_clients(self) -> Dict[str, Any]:
        """List all registered clients."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/clients"
        )
        return response.json()

    # ------------------------------------------------------------------
    # API Key Management (#16 Enterprise Foundations)
    # ------------------------------------------------------------------

    def list_keys(self) -> Dict[str, Any]:
        """List all API keys (prefix only, not full keys)."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/keys"
        )
        return response.json()

    def create_key(self, name: str) -> Dict[str, Any]:
        """Create a new API key. Returns the full key (shown once only)."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/keys",
            params={"name": name},
        )
        return response.json()

    def revoke_key(self, key_id: int) -> Dict[str, Any]:
        """Revoke an API key immediately."""
        response = self._base.request(
            "DELETE",
            f"{self._base.api_base}/keys/{key_id}",
        )
        return response.json()

    def rotate_key(self, key_id: int) -> Dict[str, Any]:
        """Rotate an API key. Old key valid for 24h grace period."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/keys/{key_id}/rotate",
        )
        return response.json()
