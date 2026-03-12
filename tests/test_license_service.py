import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import os

from desktop_app.utils.license_service import LicenseService, LicenseServiceError
from desktop_app.utils.license_dto import LicenseDisplayDTO
from license import LicenseError, Edition, get_license_file_path
from tests.test_license import _make_key, TEST_SECRET

class DummyAPIClient:
    def __init__(self, available=True, throw_error=False, return_data=None):
        self.available = available
        self.throw_error = throw_error
        self.return_data = return_data or {}
        self._base = MagicMock()
        self._base.api_base = "http://localhost:8000/api/v1"
        self._base.request = MagicMock(return_value=MagicMock(status_code=200))
        
    def is_api_available(self):
        return self.available
        
    def get_license_info(self):
        if self.throw_error:
            raise Exception("Network Timeout")
        return self.return_data

def test_fetch_license_info_no_api_client():
    service = LicenseService()
    with patch('desktop_app.utils.license_service.get_edition_display') as mock_display:
        mock_display.return_value = LicenseDisplayDTO(edition_label="Community", is_team=False, org_name="", seats=1, days_left=None, expiry_warning=False, warning_text="")
        
        result, server_error = service.fetch_license_info()
        assert result.edition_label == "Community"
        assert server_error is False
        mock_display.assert_called_once_with(None)

@patch('desktop_app.utils.app_config.get_backend_mode')
def test_fetch_license_info_api_client_error(mock_mode):
    from desktop_app.utils import app_config
    mock_mode.return_value = app_config.BACKEND_MODE_REMOTE
    client = DummyAPIClient(throw_error=True)
    service = LicenseService(api_client=client)
    
    with patch('desktop_app.utils.license_service.get_edition_display') as mock_display:
        mock_display.return_value = LicenseDisplayDTO(edition_label="Community", is_team=False, org_name="", seats=1, days_left=None, expiry_warning=False, warning_text="")
        
        # Should catch the internal exception and still return local data
        result, server_error = service.fetch_license_info()
        assert result.edition_label == "Community"
        assert server_error is True
        mock_display.assert_called_once_with(None)

@patch('desktop_app.utils.app_config.get_backend_mode')
def test_fetch_license_info_api_client_unavailable_remote_mode(mock_mode):
    from desktop_app.utils import app_config
    mock_mode.return_value = app_config.BACKEND_MODE_REMOTE
    client = DummyAPIClient(available=False)
    service = LicenseService(api_client=client)
    
    with patch('desktop_app.utils.license_service.get_edition_display') as mock_display:
        mock_display.return_value = LicenseDisplayDTO(edition_label="Team Edition", is_team=True, org_name="", seats=1, days_left=None, expiry_warning=False, warning_text="")
        
        # Should register as a server error because we are in remote mode
        result, server_error = service.fetch_license_info()
        assert result.edition_label == "Team Edition"
        assert server_error is True
        mock_display.assert_called_once_with(None)

@patch('desktop_app.utils.app_config.get_backend_mode')
def test_fetch_license_info_api_client_success(mock_mode):
    from desktop_app.utils import app_config
    mock_mode.return_value = app_config.BACKEND_MODE_REMOTE
    remote_dict = {"edition": "team"}
    client = DummyAPIClient(return_data=remote_dict)
    service = LicenseService(api_client=client)
    
    with patch('desktop_app.utils.license_service.get_edition_display') as mock_display:
        mock_display.return_value = LicenseDisplayDTO(edition_label="Team Edition", is_team=True, org_name="Test", seats=5, days_left=None, expiry_warning=False, warning_text="")
        
        result, server_error = service.fetch_license_info()
        assert result.edition_label == "Team Edition"
        assert server_error is False
        mock_display.assert_called_once_with(remote_dict)

def test_install_license_empty_key():
    service = LicenseService()
    with pytest.raises(LicenseServiceError) as exc:
        service.install_license("")
    assert exc.value.is_invalid_key_error is True
    assert "No license key" in exc.value.message

@patch('desktop_app.utils.license_service.resolve_verification_context')
@patch('desktop_app.utils.license_service.validate_license_key')
def test_install_license_invalid_key(mock_validate, mock_resolve):
    mock_resolve.return_value = ("secret", ["RS256"])
    mock_validate.side_effect = LicenseError("Expired key")
    
    service = LicenseService()
    with pytest.raises(LicenseServiceError) as exc:
        service.install_license("bad-key")
        
    assert exc.value.is_invalid_key_error is True
    assert "Expired key" in exc.value.message

@patch('desktop_app.utils.license_service.resolve_verification_context')
@patch('desktop_app.utils.license_service.validate_license_key')
@patch('desktop_app.utils.license_service.get_license_dir')
@patch('pathlib.Path.write_text')
def test_install_license_write_error_with_rollback(mock_write, mock_dir, mock_validate, mock_resolve, tmp_path):
    mock_resolve.return_value = ("secret", ["RS256"])
    mock_write.side_effect = PermissionError("Simulated write error")
    
    # Setup mock file system
    mock_dest_dir = tmp_path / "license_dir"
    mock_dest_dir.mkdir()
    mock_dir.return_value = mock_dest_dir
    
    # Create the old key directly without mocking write_text (bypass the mock temporarily or create natively)
    dest_file = mock_dest_dir / "license.key"
    with open(dest_file, "w") as f:
        f.write("old-key")
    
    service = LicenseService()
    
    with pytest.raises(LicenseServiceError) as exc:
        service.install_license("new-key")
        
    # Verify rollback logic triggered
    assert "restored from backup" in exc.value.message
    # The file content should be the old one
    with open(dest_file, "r") as f:
        assert f.read() == "old-key"

@patch('desktop_app.utils.license_service.resolve_verification_context')
@patch('desktop_app.utils.license_service.validate_license_key')
@patch('desktop_app.utils.license_service.get_license_dir')
@patch('desktop_app.utils.license_service.get_license_file_path')
@patch('desktop_app.utils.license_service.get_current_license')
@patch('desktop_app.utils.license_service.reset_license')
def test_install_license_replaces_existing_key_and_resets_cache(
    mock_reset,
    mock_current,
    mock_canonical,
    mock_dir,
    mock_validate,
    mock_resolve,
    tmp_path,
):
    mock_resolve.return_value = (TEST_SECRET, ["HS256"])
    mock_validate.side_effect = lambda key, secret, algs: None

    mock_dest_dir = tmp_path / "license_dir"
    mock_dest_dir.mkdir()
    dest_file = mock_dest_dir / "license.key"
    old_key = _make_key(edition="team", org="Old Org", seats=5, secret=TEST_SECRET)
    new_key = _make_key(edition="organization", org="New Org", seats=25, secret=TEST_SECRET)
    dest_file.write_text(old_key, encoding="utf-8")

    mock_dir.return_value = mock_dest_dir
    mock_canonical.return_value = dest_file
    mock_current.return_value = MagicMock(
        edition=Edition.ORGANIZATION,
        org_name="New Org",
        seats=25,
        expiry_timestamp=1234567890,
    )

    service = LicenseService()
    service.install_license(new_key)

    assert dest_file.read_text(encoding="utf-8") == new_key
    mock_reset.assert_called_once()
    mock_validate.assert_called_once_with(new_key, TEST_SECRET, ["HS256"])

def test_windows_license_path_resolution_uses_appdata():
    with patch('license.platform.system', return_value='Windows'):
        with patch.dict(os.environ, {'APPDATA': r'C:\Users\test\AppData\Roaming'}, clear=False):
            resolved = get_license_file_path()
    normalized = str(resolved).replace('/', '\\')
    assert normalized.endswith(r'AppData\Roaming\PGVectorRAGIndexer\license.key')

@patch('desktop_app.utils.license_service.resolve_verification_context')
@patch('desktop_app.utils.license_service.validate_license_key')
@patch('desktop_app.utils.license_service.get_license_dir')
@patch('desktop_app.utils.license_service.get_license_file_path')
@patch('desktop_app.utils.license_service.get_current_license')
@patch('desktop_app.utils.license_service.reset_license')
def test_install_license_triggers_backend_reload(
    mock_reset,
    mock_current,
    mock_canonical,
    mock_dir,
    mock_validate,
    mock_resolve,
    tmp_path,
):
    mock_resolve.return_value = (TEST_SECRET, ["HS256"])
    mock_dest_dir = tmp_path / "license_dir"
    mock_dest_dir.mkdir()
    dest_file = mock_dest_dir / "license.key"
    mock_dir.return_value = mock_dest_dir
    mock_canonical.return_value = dest_file
    mock_current.return_value = MagicMock(
        edition=Edition.ORGANIZATION,
        org_name="Reload Org",
        seats=50,
        expiry_timestamp=1234567890,
    )
    client = DummyAPIClient()

    service = LicenseService(api_client=client)
    service.install_license(_make_key(edition="organization", org="Reload Org", seats=50, secret=TEST_SECRET))

    assert client._base.request.call_count == 2
    first_call = client._base.request.call_args_list[0]
    second_call = client._base.request.call_args_list[1]
    assert first_call.args == ("POST", "http://localhost:8000/api/v1/license/install")
    assert first_call.kwargs["json"]["license_key"]
    assert second_call.args == ("POST", "http://localhost:8000/api/v1/license/reload")
    mock_reset.assert_called_once()

@patch('desktop_app.utils.license_service.resolve_verification_context')
@patch('desktop_app.utils.license_service.validate_license_key')
@patch('desktop_app.utils.license_service.get_license_dir')
@patch('pathlib.Path.write_text')
def test_install_license_rollback_preserves_original_file_contents(mock_write, mock_dir, mock_validate, mock_resolve, tmp_path):
    mock_resolve.return_value = (TEST_SECRET, ["HS256"])
    mock_write.side_effect = PermissionError("Simulated write error")

    mock_dest_dir = tmp_path / "license_dir"
    mock_dest_dir.mkdir()
    mock_dir.return_value = mock_dest_dir

    dest_file = mock_dest_dir / "license.key"
    original_key = _make_key(edition="team", org="Rollback Org", seats=5, secret=TEST_SECRET)
    with open(dest_file, "w", encoding="utf-8") as f:
        f.write(original_key)

    service = LicenseService()
    with pytest.raises(LicenseServiceError):
        service.install_license(_make_key(edition="organization", org="Rollback New", seats=25, secret=TEST_SECRET))

    assert dest_file.read_text(encoding="utf-8") == original_key
