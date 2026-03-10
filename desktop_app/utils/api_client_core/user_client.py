from typing import Dict, Any, List

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class UserClient:
    """Domain client for user management."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

    # ------------------------------------------------------------------
    # User Management (#16 Enterprise Foundations)
    # ------------------------------------------------------------------

    def list_users(self, role: str = None, active_only: bool = True) -> dict:
        """List all users, optionally filtered by role."""
        params = {"active_only": active_only}
        if role:
            params["role"] = role
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/users",
            params=params
        )
        return response.json()

    def get_user(self, user_id: str) -> dict:
        """Get a user by ID."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/users/{user_id}"
        )
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
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/users",
            json=payload
        )
        return response.json()

    def update_user(self, user_id: str, **kwargs) -> dict:
        """Update a user (admin only). Pass email, display_name, role, is_active."""
        response = self._base.request(
            "PUT",
            f"{self._base.api_base}/users/{user_id}",
            json=kwargs
        )
        return response.json()

    def delete_user(self, user_id: str) -> dict:
        """Delete a user (admin only)."""
        response = self._base.request(
            "DELETE",
            f"{self._base.api_base}/users/{user_id}"
        )
        return response.json()

    def change_user_role(self, user_id: str, role: str) -> dict:
        """Change a user's role (admin only)."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/users/{user_id}/role",
            json={"role": role}
        )
        return response.json()
        
    # ------------------------------------------------------------------
    # Roles & Permissions
    # ------------------------------------------------------------------

    def list_roles(self) -> dict:
        """List all roles with their permissions."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/roles"
        )
        return response.json()

    def get_role(self, name: str) -> dict:
        """Get a single role by name."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/roles/{name}"
        )
        return response.json()

    def list_permissions(self) -> dict:
        """List all available permissions."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/permissions"
        )
        return response.json()

    # ------------------------------------------------------------------
    # User Documents
    # ------------------------------------------------------------------

    def list_user_documents(
        self, user_id: str, visibility: str = None, limit: int = 100, offset: int = 0
    ) -> dict:
        """List documents owned by a specific user."""
        params = {"limit": limit, "offset": offset}
        if visibility:
            params["visibility"] = visibility
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/users/{user_id}/documents",
            params=params
        )
        return response.json()
