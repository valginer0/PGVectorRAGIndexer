import pytest
from unittest.mock import patch, MagicMock

from desktop_app.controllers.settings_controller import SettingsController
from desktop_app.utils.controller_result import ControllerResult, MessageSeverity, UiAction
from desktop_app.utils.controller_result import MessageSeverity
from desktop_app.utils.license_service import LicenseServiceError
from desktop_app.utils.license_dto import LicenseDisplayDTO
from desktop_app.utils import app_config

class DummyLicenseService:
    def __init__(self, throw_error=False, throw_invalid_key=False, return_data=None):
        self.throw_error = throw_error
        self.throw_invalid_key = throw_invalid_key
        self.return_data = return_data or {"edition": "community"}
        self.installed = False

    def fetch_license_info(self):
        if self.throw_error:
            raise LicenseServiceError("Local fetch failed")
            
        rd = self.return_data
        info = LicenseDisplayDTO(
            edition_label=rd.get("edition_label", "Community"),
            is_team=rd.get("is_team", False),
            org_name=rd.get("org_name", ""),
            seats=rd.get("seats", 1),
            days_left=rd.get("days_left", None),
            expiry_warning=rd.get("expiry_warning", False),
            warning_text=rd.get("warning_text", "")
        )
        return info, rd.get("server_error", False)
        
    def install_license(self, key):
        if self.throw_invalid_key:
            raise LicenseServiceError("Invalid Key", is_invalid_key_error=True)
        if self.throw_error:
            raise LicenseServiceError("Internal Error")
        self.installed = True
        
    def get_current_license_info(self):
        info = MagicMock()
        info.edition.value = "team"
        info.org_name = "Test Org"
        info.warning = "Expiring soon" if self.return_data.get("warning") else ""
        return info


def test_load_license_data_success():
    service = DummyLicenseService(return_data={"edition_label": "Team", "warning_text": ""})
    controller = SettingsController(license_service=service)
    
    result = controller.load_license_data()
    assert result.success is True
    assert result.ui_actions == [UiAction.NONE]
    assert result.data["info"].edition_label == "Team"
    assert result.data["server_error"] is False

def test_load_license_data_server_error():
    service = DummyLicenseService(return_data={"server_error": True, "warning_text": "Server Edition: Unavailable - Using Local"})
    controller = SettingsController(license_service=service)
    
    result = controller.load_license_data()
    assert result.success is True
    assert result.ui_actions == [UiAction.NONE]
    assert result.data["server_error"] is True

def test_load_license_data_hard_error():
    service = DummyLicenseService(throw_error=True)
    controller = SettingsController(license_service=service)
    
    result = controller.load_license_data()
    assert result.success is False
    assert result.severity == "warning"
    assert result.ui_actions == [UiAction.NONE]
    assert result.data["server_error"] is True

def test_install_license_success():
    service = DummyLicenseService()
    controller = SettingsController(license_service=service)
    
    result = controller.install_license("valid-key")
    assert service.installed is True
    assert result.success is True
    assert result.severity == "info"
    assert result.ui_actions == [UiAction.MESSAGE_BOX_INFO]
    assert "Test Org" in result.message

def test_install_license_success_with_warning():
    service = DummyLicenseService(return_data={"warning": True})
    controller = SettingsController(license_service=service)
    
    result = controller.install_license("valid-key")
    assert result.success is True
    assert result.severity == "warning"
    assert result.ui_actions == [UiAction.MESSAGE_BOX_WARNING]
    assert "Expiring soon" in result.message

def test_install_license_error():
    service = DummyLicenseService(throw_invalid_key=True)
    controller = SettingsController(license_service=service)
    
    result = controller.install_license("bad-key")
    assert result.success is False
    assert result.severity == "error"
    assert result.ui_actions == [UiAction.MESSAGE_BOX_ERROR]
    assert "Invalid Key" in result.message

def test_save_backend_settings_missing_url():
    controller = SettingsController()
    result = controller.save_backend_settings(app_config.BACKEND_MODE_REMOTE, "", "key")
    
    assert result.success is False
    assert result.severity == "warning"
    assert result.ui_actions == [UiAction.MESSAGE_BOX_WARNING]
    assert result.data == {} # Empty/unchanged status semantics

def test_save_backend_settings_missing_scheme():
    controller = SettingsController()
    result = controller.save_backend_settings(app_config.BACKEND_MODE_REMOTE, "foo.com", "key")
    
    assert result.success is False
    assert result.ui_actions == [UiAction.MESSAGE_BOX_WARNING]

def test_save_backend_settings_missing_api_key():
    controller = SettingsController()
    result = controller.save_backend_settings(app_config.BACKEND_MODE_REMOTE, "http://foo.com", "")
    
    assert result.success is False
    assert result.ui_actions == [UiAction.MESSAGE_BOX_WARNING]

@patch('desktop_app.utils.app_config.set_backend_mode')
@patch('desktop_app.utils.app_config.set_backend_url')
@patch('desktop_app.utils.app_config.set_api_key')
def test_save_backend_settings_success_remote(mock_key, mock_url, mock_mode):
    client = MagicMock()
    controller = SettingsController(api_client=client)
    
    result = controller.save_backend_settings(app_config.BACKEND_MODE_REMOTE, "http://foo.com", "my-key")
    assert result.success is True
    assert result.severity == "success"
    assert result.ui_actions == [UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO]
    assert result.data["status_text"] == "Settings saved."
    
    # Check underlying side-effects occurred
    mock_mode.assert_called_with(app_config.BACKEND_MODE_REMOTE)
    mock_url.assert_called_with("http://foo.com")
    mock_key.assert_called_with("my-key")
    assert client.base_url == "http://foo.com"

@patch('desktop_app.utils.app_config.set_backend_mode')
@patch('desktop_app.utils.app_config.set_api_key')
def test_save_backend_settings_success_local(mock_key, mock_mode):
    client = MagicMock()
    controller = SettingsController(api_client=client)
    
    result = controller.save_backend_settings(app_config.BACKEND_MODE_LOCAL, "http://ignored", "ignored-key")
    assert result.success is True
    assert result.ui_actions == [UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO]
    
    mock_mode.assert_called_with(app_config.BACKEND_MODE_LOCAL)
    mock_key.assert_called_with(None)
    assert client.base_url == app_config.DEFAULT_LOCAL_URL.rstrip('/')
