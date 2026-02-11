"""
Tests for Split Deployment (#2).

Tests cover:
- server-setup.sh exists and is valid bash
- server-setup-wsl.sh exists and is valid bash
- bootstrap_desktop_app.sh has --remote-backend flag
- bootstrap_desktop_app.ps1 has -RemoteBackend parameter
- DEPLOYMENT.md exists with platform support matrix
- Version compatibility endpoint exists
- app_config remote mode helpers
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Test: Server setup scripts exist
# ===========================================================================


class TestServerSetupScripts:
    def test_server_setup_sh_exists(self):
        assert (PROJECT_ROOT / "server-setup.sh").exists()

    def test_server_setup_sh_is_bash(self):
        content = (PROJECT_ROOT / "server-setup.sh").read_text()
        assert content.startswith("#!/bin/bash")

    def test_server_setup_sh_has_port_option(self):
        content = (PROJECT_ROOT / "server-setup.sh").read_text()
        assert "--port" in content

    def test_server_setup_sh_has_generate_key(self):
        content = (PROJECT_ROOT / "server-setup.sh").read_text()
        assert "--generate-key" in content

    def test_server_setup_sh_has_docker_check(self):
        content = (PROJECT_ROOT / "server-setup.sh").read_text()
        assert "docker" in content.lower()

    def test_server_setup_wsl_exists(self):
        assert (PROJECT_ROOT / "server-setup-wsl.sh").exists()

    def test_server_setup_wsl_is_bash(self):
        content = (PROJECT_ROOT / "server-setup-wsl.sh").read_text()
        assert content.startswith("#!/bin/bash")

    def test_server_setup_wsl_checks_wsl2(self):
        content = (PROJECT_ROOT / "server-setup-wsl.sh").read_text()
        assert "microsoft" in content.lower() or "wsl" in content.lower()

    def test_server_setup_wsl_delegates_to_main(self):
        content = (PROJECT_ROOT / "server-setup-wsl.sh").read_text()
        assert "server-setup.sh" in content


# ===========================================================================
# Test: Bootstrap scripts have --remote-backend
# ===========================================================================


class TestBootstrapRemoteBackend:
    def test_bash_bootstrap_has_remote_backend(self):
        content = (PROJECT_ROOT / "bootstrap_desktop_app.sh").read_text()
        assert "--remote-backend" in content

    def test_bash_bootstrap_sets_remote_mode(self):
        content = (PROJECT_ROOT / "bootstrap_desktop_app.sh").read_text()
        assert "BACKEND_MODE_REMOTE" in content

    def test_bash_bootstrap_skips_docker_in_remote(self):
        content = (PROJECT_ROOT / "bootstrap_desktop_app.sh").read_text()
        assert "REMOTE_BACKEND" in content

    def test_ps1_bootstrap_has_remote_backend(self):
        content = (PROJECT_ROOT / "bootstrap_desktop_app.ps1").read_text()
        assert "RemoteBackend" in content

    def test_ps1_bootstrap_sets_remote_mode(self):
        content = (PROJECT_ROOT / "bootstrap_desktop_app.ps1").read_text()
        assert "BACKEND_MODE_REMOTE" in content


# ===========================================================================
# Test: Deployment documentation
# ===========================================================================


class TestDeploymentDocs:
    def test_deployment_md_exists(self):
        assert (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").exists()

    def test_has_platform_support_matrix(self):
        content = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
        assert "Platform Support Matrix" in content

    def test_has_server_platforms(self):
        content = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
        assert "Linux" in content
        assert "macOS" in content
        assert "WSL2" in content

    def test_has_security_section(self):
        content = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
        assert "Security" in content

    def test_has_troubleshooting(self):
        content = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text()
        assert "Troubleshooting" in content


# ===========================================================================
# Test: Version compatibility endpoint
# ===========================================================================


class TestVersionCompatibility:
    @pytest.fixture(autouse=True)
    def _load_app(self):
        from api import app
        self.routes = {r.path for r in app.routes}

    def test_version_endpoint_exists(self):
        assert "/api/version" in self.routes


# ===========================================================================
# Test: app_config remote mode helpers
# ===========================================================================


class TestAppConfigRemoteMode:
    def test_backend_modes_defined(self):
        from desktop_app.utils.app_config import BACKEND_MODE_LOCAL, BACKEND_MODE_REMOTE
        assert BACKEND_MODE_LOCAL == "local"
        assert BACKEND_MODE_REMOTE == "remote"

    def test_default_local_url(self):
        from desktop_app.utils.app_config import DEFAULT_LOCAL_URL
        assert "localhost" in DEFAULT_LOCAL_URL

    def test_is_remote_mode_function_exists(self):
        from desktop_app.utils.app_config import is_remote_mode
        assert callable(is_remote_mode)

    def test_get_backend_url_function_exists(self):
        from desktop_app.utils.app_config import get_backend_url
        assert callable(get_backend_url)
