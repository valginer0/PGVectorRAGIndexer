from typing import Dict, Any, Optional

from desktop_app.utils.api_client_core.base_client import BaseAPIClient

class ActivityClient:
    """Domain client for the activity log."""
    
    def __init__(self, base_client: BaseAPIClient):
        self._base = base_client

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
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/activity",
            params=params
        )
        return response.json()

    def post_activity(
        self,
        action: str,
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an activity log entry."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/activity",
            json={
                "action": action,
                "client_id": client_id,
                "user_id": user_id,
                "details": details,
            }
        )
        return response.json()

    def get_activity_action_types(self) -> Dict[str, Any]:
        """Get distinct action types in the activity log."""
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/activity/actions"
        )
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
        response = self._base.request(
            "GET",
            f"{self._base.api_base}/activity/export",
            params=params
        )
        return response.text

    def apply_activity_retention(self, days: int) -> Dict[str, Any]:
        """Apply retention policy — delete entries older than N days."""
        response = self._base.request(
            "POST",
            f"{self._base.api_base}/activity/retention",
            json={"days": days}
        )
        return response.json()
