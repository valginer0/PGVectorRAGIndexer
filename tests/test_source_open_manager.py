import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
import sys
import os

from desktop_app.ui.source_open_manager import SourceOpenManager

@pytest.fixture
def mock_api_client():
    return MagicMock()

@pytest.fixture
def source_manager(mock_api_client):
    # Mock project root
    project_root = Path("/mock/project")
    return SourceOpenManager(mock_api_client, project_root=project_root)

def test_normalize_path_exists(source_manager):
    """Test that existing paths are normalized correctly."""
    with patch("pathlib.Path.exists", return_value=True):
        
        path = "/home/user/file.txt"
        normalized = source_manager._normalize_path(path)
        assert normalized == Path(path)

def test_normalize_path_not_exists_no_resolve(source_manager):
    """Test that non-existent paths return None if resolution fails."""
    with patch("pathlib.Path.exists", return_value=False), \
         patch.object(source_manager, "_resolve_path_mismatch", return_value=None), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        
        path = "/home/user/missing.txt"
        normalized = source_manager._normalize_path(path)
        assert normalized is None
        mock_warn.assert_called_once()

def test_resolve_path_mismatch_success(source_manager):
    """Test successful path resolution."""
    original_path = "C:\\Users\\User\\Documents\\resume.pdf"
    expected_path = Path("/mock/project/documents/resume.pdf")
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", return_value=[expected_path]):
        
        resolved = source_manager._resolve_path_mismatch(original_path)
        assert resolved == expected_path

def test_resolve_path_mismatch_failure(source_manager):
    """Test failed path resolution."""
    original_path = "C:\\Users\\User\\Documents\\missing.pdf"
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.rglob", return_value=[]):
        
        resolved = source_manager._resolve_path_mismatch(original_path)
        assert resolved is None

def test_is_wsl_true(source_manager):
    """Test WSL detection returns True."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", new_callable=MagicMock) as mock_open:
        
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version ... microsoft-standard-WSL2"
        mock_open.return_value.__enter__.return_value = mock_file
        
        assert source_manager._is_wsl() is True

def test_is_wsl_false(source_manager):
    """Test WSL detection returns False."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", new_callable=MagicMock) as mock_open:
        
        mock_file = MagicMock()
        mock_file.read.return_value = "Linux version ... generic"
        mock_open.return_value.__enter__.return_value = mock_file
        
        assert source_manager._is_wsl() is False

def test_open_in_wsl_success(source_manager):
    """Test opening file in WSL."""
    linux_path = Path("/home/user/doc.txt")
    windows_path = r"\\wsl.localhost\Ubuntu\home\user\doc.txt"
    
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        
        # Mock wslpath output
        mock_run.return_value.stdout = windows_path
        
        source_manager._open_in_wsl(linux_path)
        
        # Verify wslpath called
        mock_run.assert_called_with(
            ["wslpath", "-w", str(linux_path)],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Verify cmd.exe called
        mock_popen.assert_called_with(
            ["cmd.exe", "/c", "start", "", windows_path]
        )
