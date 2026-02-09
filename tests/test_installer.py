import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys
import json
import tempfile
import shutil

# Add parent dir to path to import installer_logic
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'windows_installer')))

from installer_logic import Installer, InstallStep

@unittest.skipUnless(sys.platform == 'win32', "Windows-specific installer tests")
class TestInstallerLogic(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.installer = Installer(install_dir=self.test_dir)
        # Mock logging to avoid clutter
        self.installer._log = MagicMock()
        self.installer._update_progress = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch('subprocess.Popen')
    @patch('os.path.exists')
    def test_start_runtime_rdctl_success(self, mock_exists, mock_popen):
        """Test that start_runtime uses rdctl correctly."""
        # Setup mocks
        # partial side effect to allow temp dir checks but force rdctl existence
        def side_effect(path):
            if "rdctl.exe" in path:
                return True
            return os.path.exists(path) if not "rdctl.exe" in str(path) else True
        
        mock_exists.side_effect = side_effect
        
        # Test helper directly
        result = self.installer._start_runtime_helper()
        
        self.assertTrue(result)
        # Verify Popen called with correct args
        args, kwargs = mock_popen.call_args
        command = args[0]
        self.assertIn("rdctl.exe", command)
        self.assertIn("start", command)
        self.assertIn("--container-engine moby", command)

    @patch('installer_logic.Installer._run_command')
    @patch('installer_logic.Installer._start_runtime_helper')
    def test_step_start_runtime_already_running(self, mock_helper, mock_run):
        """Test that we skip starting if docker ps succeeds."""
        mock_run.return_value = (True, "CONTAINER ID...") # docker ps succeeds
        
        result = self.installer._step_start_runtime()
        
        self.assertTrue(result)
        mock_helper.assert_not_called()

    @patch('installer_logic.Installer.request_reboot')
    @patch('installer_logic.Installer._run_command')
    @patch('installer_logic.Installer._start_runtime_helper')
    @patch('time.sleep') # Don't actually sleep
    @patch('time.time')
    def test_step_start_runtime_failure_triggers_reboot(self, mock_time, mock_sleep, mock_helper, mock_run, mock_reboot):
        """Test that if runtime fails to start, we trigger reboot."""
        # 1. docker ps fails initially
        # 2. start_runtime_helper returns False (failed to launch) OR True but docker ps never succeeds
        
        # Scenario: Start helper says "I launched it", but docker ps keeps failing
        mock_run.return_value = (False, "error")
        mock_helper.return_value = True
        
        # Control time loop
        mock_time.side_effect = [0, 0, 301] # Start, Loop check (ok), Loop check (timeout)
        
        result = self.installer._step_start_runtime()
        
        self.assertFalse(result)
        mock_reboot.assert_called_once()


    @patch('subprocess.run')
    def test_request_reboot_state_and_task(self, mock_subprocess):
        """Test request_reboot saves state and schedules task."""
        # Mock checking for file existence to return False initially
        
        self.installer.request_reboot()
        
        # 1. Check State File Created
        self.assertTrue(os.path.exists(self.installer.state_file))
        with open(self.installer.state_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['Stage'], "PostReboot")
            self.assertEqual(state['InstallDir'], self.test_dir)
            
        # 2. Check Scheduled Task Command
        mock_subprocess.assert_called()
        cmd_arg = mock_subprocess.call_args[0][0]
        self.assertIn('schtasks /create', cmd_arg)
        self.assertIn('PGVectorRAGIndexer_Resume', cmd_arg)
        self.assertIn('/sc onlogon', cmd_arg)

    def test_resume_logic_skips_steps(self):
        """Test that run() skips steps if state file exists."""
        # Manually create state file
        with open(self.installer.state_file, 'w') as f:
            json.dump({"Stage": "PostReboot"}, f)
            
        # Mock step functions
        self.installer._step_check_system = MagicMock()
        self.installer._step_install_docker = MagicMock() # Step 4
        self.installer._step_start_runtime = MagicMock(return_value=True) # Step 5
        self.installer._step_finalize = MagicMock(return_value=True)
        
        # Don't actually run real logic
        with patch.object(self.installer, '_load_state', wraps=self.installer._load_state) as mock_load:
            self.installer.run()
            
            # Check System (Step 1) should NOT be called
            self.installer._step_check_system.assert_not_called()
            
            # Start Runtime (Step 5) SHOULD be called
            self.installer._step_start_runtime.assert_called()
            
            # State should be cleared
            self.assertFalse(os.path.exists(self.installer.state_file))

    @patch('installer_logic.Installer._run_command_stream')
    @patch('installer_logic.Installer._run_command')
    def test_step_pull_images_needs_download(self, mock_run, mock_stream):
        """Test image pulling when images are NOT cached locally."""
        # First call: app image not found, second call: db image not found
        mock_run.side_effect = [
            (True, ""),   # docker images -q app → empty = not found
            (True, ""),   # docker images -q db  → empty = not found
        ]
        mock_stream.return_value = True

        result = self.installer._step_pull_images()

        self.assertTrue(result)
        mock_stream.assert_called_once_with("docker compose pull")

    @patch('installer_logic.Installer._run_command_stream')
    @patch('installer_logic.Installer._run_command')
    def test_step_pull_images_skips_when_cached(self, mock_run, mock_stream):
        """Test image pulling is skipped when both images exist locally."""
        mock_run.side_effect = [
            (True, "sha256:abc123\n"),  # app image exists
            (True, "sha256:def456\n"),  # db image exists
        ]

        result = self.installer._step_pull_images()

        self.assertTrue(result)
        mock_stream.assert_not_called()  # Should NOT pull

    # =======================================================================
    # Docker Detection Improvement Tests
    # =======================================================================

    @patch('installer_logic.Installer._run_command')
    def test_check_virtualization_enabled_powershell_true(self, mock_run):
        """Test virtualization check returns True when PowerShell reports enabled."""
        mock_run.return_value = (True, "True\n")
        result = self.installer._check_virtualization_enabled()
        self.assertTrue(result)
        # Verify PowerShell was used (not systeminfo)
        cmd = mock_run.call_args[0][0]
        self.assertIn("Get-CimInstance", cmd)

    @patch('installer_logic.Installer._run_command')
    def test_check_virtualization_enabled_powershell_false(self, mock_run):
        """Test virtualization check returns False when PowerShell reports disabled."""
        mock_run.return_value = (True, "False\n")
        result = self.installer._check_virtualization_enabled()
        self.assertFalse(result)

    @patch('installer_logic.Installer._run_command')
    def test_check_virtualization_enabled_fallback_systeminfo(self, mock_run):
        """Test fallback to systeminfo when PowerShell fails."""
        def side_effect(cmd, **kwargs):
            if 'Get-CimInstance' in cmd:
                return (False, "error")  # PowerShell fails
            if cmd == 'systeminfo':
                return (True, "Virtualization Enabled In Firmware: Yes\n")
            return (False, "")
        mock_run.side_effect = side_effect
        result = self.installer._check_virtualization_enabled()
        self.assertTrue(result)

    @patch('installer_logic.Installer._run_command')
    def test_check_architecture_x64(self, mock_run):
        """Test x64 architecture detection."""
        mock_run.return_value = (True, "AMD64\n")
        result = self.installer._check_architecture()
        self.assertEqual(result, 'x64')

    @patch('installer_logic.Installer._run_command')
    def test_check_architecture_arm64(self, mock_run):
        """Test ARM64 architecture detection."""
        mock_run.return_value = (True, "ARM64\n")
        result = self.installer._check_architecture()
        self.assertEqual(result, 'ARM64')

    @patch('installer_logic.Installer._run_command')
    def test_get_computer_manufacturer_dell(self, mock_run):
        """Test Dell manufacturer detection."""
        mock_run.return_value = (True, "Dell Inc.\n")
        result = self.installer._get_computer_manufacturer()
        self.assertEqual(result, 'Dell')

    @patch('installer_logic.Installer._run_command')
    def test_get_computer_manufacturer_hp(self, mock_run):
        """Test HP manufacturer detection."""
        mock_run.return_value = (True, "Hewlett-Packard\n")
        result = self.installer._get_computer_manufacturer()
        self.assertEqual(result, 'HP')

    @patch('installer_logic.Installer._run_command')
    def test_get_computer_manufacturer_unknown(self, mock_run):
        """Test unknown manufacturer fallback."""
        mock_run.return_value = (False, "")
        result = self.installer._get_computer_manufacturer()
        self.assertEqual(result, 'Unknown')

    @patch('os.path.exists')
    def test_check_docker_desktop_installed_by_path(self, mock_exists):
        """Test Docker Desktop detection via file path."""
        original_exists = os.path.exists
        def side_effect(path):
            if 'Docker Desktop.exe' in str(path):
                return True
            return original_exists(path)
        mock_exists.side_effect = side_effect
        result = self.installer._check_docker_desktop_installed()
        self.assertTrue(result)

    @patch('os.path.exists', return_value=False)
    @patch('installer_logic.Installer._run_command')
    def test_check_docker_desktop_installed_by_registry(self, mock_run, mock_exists):
        """Test Docker Desktop detection via registry when file paths don't exist."""
        def side_effect(cmd, **kwargs):
            if 'HKLM' in cmd and 'Docker' in cmd:
                return (True, "Version    REG_SZ    4.30.0\n")
            return (False, "")
        mock_run.side_effect = side_effect
        result = self.installer._check_docker_desktop_installed()
        self.assertTrue(result)

    @patch('installer_logic.Installer._run_command')
    def test_check_podman_installed_running(self, mock_run):
        """Test Podman detection when podman ps succeeds."""
        mock_run.return_value = (True, "CONTAINER ID...")
        result = self.installer._check_podman_installed()
        self.assertTrue(result)

    @patch('installer_logic.Installer._check_command')
    @patch('installer_logic.Installer._run_command')
    def test_check_podman_installed_not_running(self, mock_run, mock_check):
        """Test Podman detection when podman ps fails but binary exists."""
        mock_run.return_value = (False, "error")
        mock_check.return_value = True
        result = self.installer._check_podman_installed()
        self.assertTrue(result)

    @patch('installer_logic.Installer._check_command')
    @patch('installer_logic.Installer._run_command')
    def test_setup_podman_docker_compat_with_podman_docker(self, mock_run, mock_check):
        """Test Podman-Docker compat when podman-docker package provides compose."""
        def side_effect(cmd, **kwargs):
            if cmd == "docker --version":
                return (True, "podman version 4.9.0")
            if cmd == "docker compose version":
                return (True, "Docker Compose version v2.24.0")
            return (False, "")
        mock_run.side_effect = side_effect
        mock_check.return_value = False
        result = self.installer._setup_podman_docker_compat()
        self.assertTrue(result)

    @patch('installer_logic.Installer._check_command')
    @patch('installer_logic.Installer._run_command')
    def test_setup_podman_docker_compat_no_compose(self, mock_run, mock_check):
        """Test Podman-Docker compat fails when compose is not available."""
        mock_run.return_value = (False, "error")
        mock_check.return_value = False  # No podman-compose either
        result = self.installer._setup_podman_docker_compat()
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
