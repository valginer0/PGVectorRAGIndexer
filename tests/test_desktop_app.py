"""
Tests for desktop application components.

Note: These are basic import and initialization tests.
Full GUI testing would require a display server and is beyond scope.
"""

import pytest
import sys
from pathlib import Path


def test_desktop_app_imports():
    """Test that desktop app modules can be imported."""
    try:
        from desktop_app.utils.api_client import APIClient
        from desktop_app.utils.docker_manager import DockerManager
        assert APIClient is not None
        assert DockerManager is not None
    except ImportError as e:
        pytest.skip(f"Desktop app dependencies not installed: {e}")


def test_api_client_initialization():
    """Test API client can be initialized."""
    try:
        from desktop_app.utils.api_client import APIClient
        
        client = APIClient("http://localhost:8000")
        assert client.base_url == "http://localhost:8000"
        assert client.timeout == 300
    except ImportError:
        pytest.skip("Desktop app dependencies not installed")


def test_docker_manager_initialization():
    """Test Docker manager can be initialized."""
    try:
        from desktop_app.utils.docker_manager import DockerManager
        
        project_path = Path(__file__).parent.parent
        manager = DockerManager(project_path)
        assert manager.project_path == project_path
    except ImportError:
        pytest.skip("Desktop app dependencies not installed")


def test_docker_manager_windows_detection():
    """Test Docker manager detects Windows correctly."""
    try:
        from desktop_app.utils.docker_manager import DockerManager
        import platform
        
        project_path = Path(__file__).parent.parent
        manager = DockerManager(project_path)
        
        # Should match platform detection
        assert manager.is_windows == (platform.system() == "Windows")
    except ImportError:
        pytest.skip("Desktop app dependencies not installed")


def test_requirements_desktop_exists():
    """Test that requirements-desktop.txt exists."""
    req_file = Path(__file__).parent.parent / "requirements-desktop.txt"
    assert req_file.exists(), "requirements-desktop.txt should exist"
    
    # Check it contains PySide6
    content = req_file.read_text()
    assert "PySide6" in content, "requirements-desktop.txt should include PySide6"
    assert "requests" in content, "requirements-desktop.txt should include requests"


def test_launch_scripts_exist():
    """Test that launch scripts exist."""
    project_root = Path(__file__).parent.parent
    
    bat_file = project_root / "run_desktop_app.bat"
    sh_file = project_root / "run_desktop_app.sh"
    
    assert bat_file.exists(), "run_desktop_app.bat should exist"
    assert sh_file.exists(), "run_desktop_app.sh should exist"


def test_desktop_app_structure():
    """Test that desktop app directory structure is correct."""
    project_root = Path(__file__).parent.parent
    desktop_app = project_root / "desktop_app"
    
    assert desktop_app.exists(), "desktop_app directory should exist"
    assert (desktop_app / "__init__.py").exists()
    assert (desktop_app / "main.py").exists()
    assert (desktop_app / "ui").exists()
    assert (desktop_app / "utils").exists()
    assert (desktop_app / "ui" / "__init__.py").exists()
    assert (desktop_app / "utils" / "__init__.py").exists()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-specific test"
)
def test_windows_batch_file_syntax():
    """Test that Windows batch file has correct syntax."""
    project_root = Path(__file__).parent.parent
    bat_file = project_root / "run_desktop_app.bat"
    
    content = bat_file.read_text()
    
    # Check for key commands
    assert "@echo off" in content
    assert "python -m desktop_app.main" in content
    assert "venv-windows" in content
