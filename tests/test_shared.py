import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import sys
import subprocess

from desktop_app.ui.shared import system_open, _is_wsl, _open_in_wsl

def test_system_open_windows():
    """Test system_open on Windows."""
    path = Path("C:/file.txt")
    with patch("sys.platform", "win32"), \
         patch("os.startfile", create=True) as mock_startfile:
        
        system_open(path)
        mock_startfile.assert_called_once_with(str(path))

def test_system_open_macos():
    """Test system_open on macOS."""
    path = Path("/Users/user/file.txt")
    with patch("sys.platform", "darwin"), \
         patch("subprocess.Popen") as mock_popen:
        
        system_open(path)
        mock_popen.assert_called_once_with(["open", str(path)])

def test_system_open_linux_native():
    """Test system_open on Linux (native)."""
    path = Path("/home/user/file.txt")
    with patch("sys.platform", "linux"), \
         patch("desktop_app.ui.shared._is_wsl", return_value=False), \
         patch("subprocess.Popen") as mock_popen:
        
        system_open(path)
        mock_popen.assert_called_once_with(["xdg-open", str(path)])

def test_system_open_linux_fallback():
    """Test system_open fallback to webbrowser on Linux."""
    path = Path("/home/user/file.txt")
    with patch("sys.platform", "linux"), \
         patch("desktop_app.ui.shared._is_wsl", return_value=False), \
         patch("subprocess.Popen", side_effect=FileNotFoundError), \
         patch("webbrowser.open") as mock_web_open:
        
        system_open(path)
        mock_web_open.assert_called_once_with(path.as_uri())

def test_system_open_wsl():
    """Test system_open in WSL."""
    path = Path("/home/user/file.txt")
    with patch("sys.platform", "linux"), \
         patch("desktop_app.ui.shared._is_wsl", return_value=True), \
         patch("desktop_app.ui.shared._open_in_wsl") as mock_wsl_open:
        
        system_open(path)
        mock_wsl_open.assert_called_once_with(path)

def test_is_wsl_true():
    """Test _is_wsl returns True."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", mock_open(read_data="Microsoft")):
        assert _is_wsl() is True

def test_is_wsl_false():
    """Test _is_wsl returns False."""
    with patch("sys.platform", "linux"), \
         patch("builtins.open", mock_open(read_data="Linux")):
        assert _is_wsl() is False

def test_open_in_wsl_success():
    """Test _open_in_wsl success."""
    linux_path = Path("/home/user/doc.txt")
    windows_path = r"\\wsl.localhost\Ubuntu\home\user\doc.txt"
    
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        
        mock_run.return_value.stdout = windows_path
        
        _open_in_wsl(linux_path)
        
        mock_run.assert_called_with(
            ["wslpath", "-w", str(linux_path)],
            capture_output=True,
            text=True,
            check=True
        )
        mock_popen.assert_called_with(
            ["cmd.exe", "/c", "start", "", windows_path]
        )
