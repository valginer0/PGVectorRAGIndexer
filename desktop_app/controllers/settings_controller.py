import logging
from typing import Optional
import requests

from desktop_app.utils.controller_result import (
    ControllerResult,
    MessageSeverity,
    UiAction,
    LicenseLoadData,
    BackendSaveData,
    EmptyData
)
from desktop_app.utils.license_service import LicenseService, LicenseServiceError
from desktop_app.utils import app_config
from license import get_license_file_path

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
            info, server_error = self.license_service.fetch_license_info()
                
            return ControllerResult(
                success=True,
                message="Loaded.",
                severity=MessageSeverity.INFO,
                ui_actions=[UiAction.NONE],
                data=LicenseLoadData(info=info, server_error=server_error)
            )
        except LicenseServiceError as e:
            return ControllerResult(
                success=False,
                message=str(e),
                severity=MessageSeverity.WARNING,
                ui_actions=[UiAction.NONE],
                data=LicenseLoadData(info=None, server_error=True)
            )

    def install_license(self, key_string: str) -> ControllerResult[EmptyData]:
        """Attempts to install a new license key."""
        try:
            self.license_service.install_license(key_string)
            info = self.license_service.get_current_license_info()
            resolved_path = get_license_file_path()
             
            # Format success message
            if info.warning:
                msg = (
                    f"Edition: {info.edition.value.title()}\n"
                    f"Organization: {info.org_name}\n"
                    f"Saved to: {resolved_path}\n\n"
                    f"⚠️ Warning: {info.warning}"
                )
                severity = MessageSeverity.WARNING
                ui_action = UiAction.MESSAGE_BOX_WARNING
            else:
                msg = (
                    f"Edition: {info.edition.value.title()}\n"
                    f"Organization: {info.org_name}\n"
                    f"Saved to: {resolved_path}\n\n"
                    "The application has been updated with your new license."
                )
                severity = MessageSeverity.INFO
                ui_action = UiAction.MESSAGE_BOX_INFO
                
            return ControllerResult(
                success=True,
                message=msg,
                severity=severity,
                ui_actions=[ui_action],
                data=EmptyData()
            )
            
        except LicenseServiceError as e:
            # Domain error from the service boundary
            return ControllerResult(
                success=False,
                message=str(e),
                severity=MessageSeverity.ERROR,
                ui_actions=[UiAction.MESSAGE_BOX_ERROR],
                data=EmptyData()
            )
        except Exception as e:
            logger.error("Unexpected error in controller install_license: %s", e, exc_info=True)
            return ControllerResult(
                success=False,
                message=f"An unexpected error occurred:\n{e}",
                severity=MessageSeverity.ERROR,
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
                    severity=MessageSeverity.WARNING,
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
            if not url.startswith(("http://", "https://")):
                return ControllerResult(
                    success=False,
                    message="Backend URL must start with http:// or https://",
                    severity=MessageSeverity.WARNING,
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
            if not api_key:
                return ControllerResult(
                    success=False,
                    message="An API key is required for remote connections.",
                    severity=MessageSeverity.WARNING,
                    ui_actions=[UiAction.MESSAGE_BOX_WARNING],
                    data=BackendSaveData()
                )
                
            app_config.set_backend_mode(mode)
            app_config.set_backend_url(url)
            app_config.set_api_key(api_key)
            
            # Update live client
            if self.api_client:
                self.api_client.base_url = url
                self.api_client._api_key = api_key
                
        else:
            app_config.set_backend_mode(app_config.BACKEND_MODE_LOCAL)
            app_config.set_api_key(None)
            
            if self.api_client:
                self.api_client.base_url = app_config.DEFAULT_LOCAL_URL
                self.api_client._api_key = None

        msg = (
            f"Mode: {mode.title()}\n"
            f"URL: {url if mode == app_config.BACKEND_MODE_REMOTE else app_config.DEFAULT_LOCAL_URL}\n\n"
            "The app will use these settings immediately."
        )

        return ControllerResult(
            success=True,
            message=msg,
            severity=MessageSeverity.SUCCESS,
            ui_actions=[UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO],
            data=BackendSaveData(status_text="Settings saved.")
        )

    def test_connection(self, url: str, api_key: str) -> ControllerResult[BackendSaveData]:
        """Polls the `/api/version` endpoint to verify connection."""
        if not url:
            return ControllerResult(
                success=False,
                message="Enter a URL first.",
                severity=MessageSeverity.WARNING,
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="Enter a URL first.")
            )

        if not url.startswith(("http://", "https://")):
            return ControllerResult(
                success=False,
                message="URL must start with http:// or https://",
                severity=MessageSeverity.WARNING,
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="URL must start with http:// or https://")
            )

        try:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            resp = requests.get(f"{url.rstrip('/')}/api/version", headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                server_ver = data.get("server_version", "?")
                
                return ControllerResult(
                    success=True,
                    message="Connected",
                    severity=MessageSeverity.SUCCESS,
                    ui_actions=[UiAction.STATUS_LABEL],
                    data=BackendSaveData(status_text=f"Connected — server v{server_ver}")
                )
            elif resp.status_code == 401:
                return ControllerResult(
                    success=False,
                    message="Auth failed",
                    severity=MessageSeverity.ERROR,
                    ui_actions=[UiAction.STATUS_LABEL],
                    data=BackendSaveData(status_text="Authentication failed — check API key.")
                )
            else:
                return ControllerResult(
                    success=False,
                    message=f"HTTP {resp.status_code}",
                    severity=MessageSeverity.WARNING,
                    ui_actions=[UiAction.STATUS_LABEL],
                    data=BackendSaveData(status_text=f"Server returned HTTP {resp.status_code}")
                )
        except requests.exceptions.Timeout:
            return ControllerResult(
                success=False,
                message="Connection Error",
                severity=MessageSeverity.ERROR,
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="Connection timed out.")
            )
        except requests.exceptions.RequestException as e:
            return ControllerResult(
                success=False,
                message="Connection Error",
                severity=MessageSeverity.ERROR,
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text="Connection refused — is the server running?")
            )
        except Exception as e:
            return ControllerResult(
                success=False,
                message=str(e),
                severity=MessageSeverity.ERROR,
                ui_actions=[UiAction.STATUS_LABEL],
                data=BackendSaveData(status_text=f"Error: {e}")
            )

