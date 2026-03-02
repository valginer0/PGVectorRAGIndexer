import logging
from typing import Optional
import urllib.request
import urllib.error

from desktop_app.utils.controller_result import (
    ControllerResult,
    UiAction,
    LicenseLoadData,
    BackendSaveData,
    EmptyData
)
from desktop_app.utils.license_service import LicenseService, LicenseServiceError
from desktop_app.utils import app_config

logger = logging.getLogger(__name__)

class SettingsController:
    """
    Orchestrates logic for the Settings tab.
    Maps service-layer states and errors into strongly-typed ControllerResult payloads 
    that rigidly dictate the UI's actions.
    """

    def __init__(self, api_client=None, license_service: Optional[LicenseService] = None):
        self.api_client = api_client
        self.license_service = license_service or LicenseService(api_client=api_client)

    def load_license_data(self) -> ControllerResult[LicenseLoadData]:
        """Loads current license information for display."""
        try:
            info = self.license_service.fetch_license_info()
            server_error = False
            
            # Additional heuristic: if info mentions it fell back to local due to server issue
            if "Server Edition: Unavailable" in str(info.get("warning_text", "")):
                server_error = True
                
            return ControllerResult(
                success=True,
                message="Loaded.",
                severity="info",
                ui_actions=[UiAction.NONE],
                data=LicenseLoadData(info=info, server_error=server_error)
            )
        except LicenseServiceError as e:
            return ControllerResult(
                success=False,
                message=str(e),
                severity="warning",
                ui_actions=[UiAction.NONE],
                data=LicenseLoadData(info={}, server_error=True)
            )

    def install_license(self, key_string: str) -> ControllerResult[EmptyData]:
        """Attempts to install a new license key."""
        try:
            self.license_service.install_license(key_string)
            info = self.license_service.get_current_license_info()
            
            # Format success message
            if info.warning:
                msg = (
                    f"Edition: {info.edition.value.title()}\n"
                    f"Organization: {info.org_name}\n\n"
                    f"⚠️ Warning: {info.warning}"
                )
                severity = "warning"
            else:
                msg = (
                    f"Edition: {info.edition.value.title()}\n"
                    f"Organization: {info.org_name}\n\n"
                    "The application has been updated with your new license."
                )
                severity = "info"
                
            return ControllerResult(
                success=True,
                message=msg,
                severity=severity,
                ui_actions=[UiAction.MESSAGE_BOX_INFO],
                data=EmptyData()
            )
            
        except LicenseServiceError as e:
            # Domain error from the service boundary
            return ControllerResult(
                success=False,
                message=str(e),
                severity="error",
                ui_actions=[UiAction.MESSAGE_BOX_ERROR],
                data=EmptyData()
            )
        except Exception as e:
            logger.error("Unexpected error in controller install_license: %s", e, exc_info=True)
            return ControllerResult(
                success=False,
                message=f"An unexpected error occurred:\n{e}",
                severity="error",
                ui_actions=[UiAction.MESSAGE_BOX_ERROR],
                data=EmptyData()
            )

    def save_backend_settings(self, mode: str, url: str, api_key: str) -> ControllerResult[BackendSaveData]:
        """Validates and persists the backend connection string settings."""
        if mode == app_config.BACKEND_MODE_REMOTE:
            if not url:
                return ControllerResult(
                    success=False,
                    message="Please enter a backend URL.",
                    severity="warning",
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
            if not url.startswith(("http://", "https://")):
                return ControllerResult(
                    success=False,
                    message="Backend URL must start with http:// or https://",
                    severity="warning",
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
            if not api_key:
                return ControllerResult(
                    success=False,
                    message="An API key is required for remote connections.",
                    severity="warning",
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
                
            app_config.set_backend_mode(mode)
            app_config.set_backend_url(url)
            app_config.set_api_key(api_key)
            
            # Update live client
            if self.api_client:
                self.api_client.base_url = url.rstrip('/')
                self.api_client.api_base = f"{self.api_client.base_url}/api/v1"
                self.api_client._api_key = api_key
                
        else:
            app_config.set_backend_mode(app_config.BACKEND_MODE_LOCAL)
            app_config.set_api_key(None)
            
            if self.api_client:
                self.api_client.base_url = app_config.DEFAULT_LOCAL_URL.rstrip('/')
                self.api_client.api_base = f"{self.api_client.base_url}/api/v1"
                self.api_client._api_key = None

        msg = (
            f"Mode: {mode.title()}\n"
            f"URL: {url if mode == app_config.BACKEND_MODE_REMOTE else app_config.DEFAULT_LOCAL_URL}\n\n"
            "The app will use these settings immediately."
        )

        return ControllerResult(
            success=True,
            message=msg,
            severity="success",
            ui_actions=[UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO],
            data=BackendSaveData(status_text="Settings saved.")
        )

    def test_connection(self, url: str, api_key: str) -> ControllerResult[BackendSaveData]:
        """Polls the `/api/version` endpoint to verify connection."""
        if not url:
            return ControllerResult(
                success=False,
                message="Enter a URL first.",
                severity="warning",
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="Enter a URL first.")
            )

        if not url.startswith(("http://", "https://")):
            return ControllerResult(
                success=False,
                message="URL must start with http:// or https://",
                severity="warning",
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="URL must start with http:// or https://")
            )

        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/api/version", method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    import json
                    body = resp.read()
                    data = json.loads(body)
                    server_ver = data.get("server_version", "?")
                    
                    return ControllerResult(
                        success=True,
                        message="Connected",
                        severity="success",
                        ui_actions=[UiAction.STATUS_LABEL],
                        data=BackendSaveData(status_text=f"Connected — server v{server_ver}")
                    )
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return ControllerResult(
                    success=False,
                    message="Auth failed",
                    severity="error",
                    ui_actions=[UiAction.STATUS_LABEL],
                    data=BackendSaveData(status_text="Authentication failed — check API key.")
                )
            return ControllerResult(
                success=False,
                message=f"HTTP {e.code}",
                severity="warning",
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text=f"Server returned HTTP {e.code}")
            )
        except urllib.error.URLError as e:
            text = "Connection timed out." if isinstance(e.reason, TimeoutError) else "Connection refused — is the server running?"
            return ControllerResult(
                success=False,
                message="Connection Error",
                severity="error",
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text=text)
            )
        except Exception as e:
            return ControllerResult(
                success=False,
                message=str(e),
                severity="error",
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text=f"Error: {e}")
            )

