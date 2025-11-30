import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QPushButton, QLabel
from PySide6.QtCore import Qt

from desktop_app.ui.upload_tab import UploadTab

@pytest.fixture(scope="session")
def qapp():
    """Create the QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def mock_api_client():
    return MagicMock()

@pytest.fixture
def upload_tab(qapp, mock_api_client):
    tab = UploadTab(mock_api_client)
    # Force show to ensure visibility checks work as expected in some environments
    tab.show() 
    return tab

def test_initialization(upload_tab):
    """Test that UI components are initialized correctly."""
    assert upload_tab.api_client is not None
    assert upload_tab.failed_uploads == []
    
    # Check for key widgets
    assert hasattr(upload_tab, "select_files_btn")
    assert hasattr(upload_tab, "upload_btn")
    assert hasattr(upload_tab, "view_errors_btn")
    
    # Check initial state of error button
    # It is explicitly hidden in setup_ui
    assert not upload_tab.view_errors_btn.isVisible()

def test_upload_workflow(upload_tab, mock_api_client):
    """Test the upload workflow."""
    # Mock file selection
    files = [Path("/path/to/file1.txt"), Path("/path/to/file2.pdf")]
    upload_tab.selected_files = files
    
    # Mock UploadWorker
    with patch("desktop_app.ui.upload_tab.UploadWorker") as MockWorker:
        mock_worker_instance = MockWorker.return_value
        
        # Trigger upload
        upload_tab.upload_file()
        
        # Verify worker started
        MockWorker.assert_called_once()
        mock_worker_instance.start.assert_called_once()
        
        # Verify UI state during upload
        assert not upload_tab.upload_btn.isEnabled()

def test_upload_failure_handling(upload_tab):
    """Test that failed uploads are recorded and error button appears."""
    # Reset state
    upload_tab.failed_uploads = []
    upload_tab.view_errors_btn.hide()
    upload_tab.selected_files = [Path("bad_file.txt")]
    
    # Simulate a failed upload
    # on_file_finished(index, success, message)
    error_msg = "Connection timed out"
    upload_tab.on_file_finished(0, False, error_msg)
    
    # Verify failure recorded
    assert len(upload_tab.failed_uploads) == 1
    assert upload_tab.failed_uploads[0]["file"] == "bad_file.txt"
    assert upload_tab.failed_uploads[0]["error"] is not None
    assert "Hint" in upload_tab.failed_uploads[0]["error"]
    
    # Verify button visibility
    assert upload_tab.view_errors_btn.isVisible()

def test_upload_success_handling(upload_tab):
    """Test that successful uploads do not trigger error handling."""
    # Reset state
    upload_tab.failed_uploads = []
    upload_tab.view_errors_btn.hide()
    upload_tab.selected_files = [Path("good_file.txt")]
    
    # Simulate a successful upload
    upload_tab.on_file_finished(0, True, "Success")
    
    # Verify no failure recorded
    assert len(upload_tab.failed_uploads) == 0
    assert not upload_tab.view_errors_btn.isVisible()

def test_clear_failures_on_new_upload(upload_tab):
    """Test that previous failures are cleared when starting a new upload."""
    # Setup previous failures
    upload_tab.failed_uploads = [{"file": "old.txt", "error": "old error"}]
    upload_tab.view_errors_btn.show()
    upload_tab.selected_files = [Path("/path/to/new.txt")]
    
    # Mock UploadWorker
    with patch("desktop_app.ui.upload_tab.UploadWorker"):
        # Start new upload
        upload_tab.upload_file()
        
        # Verify failures cleared
        assert upload_tab.failed_uploads == []
        assert not upload_tab.view_errors_btn.isVisible()
