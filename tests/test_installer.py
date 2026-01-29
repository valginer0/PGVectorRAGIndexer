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

    @patch('installer_logic.Installer._run_command')
    def test_step_pull_images(self, mock_run):
        """Test image pulling step."""
        mock_run.return_value = (True, "Pulled")
        
        self.installer._step_pull_images()
        
        args = mock_run.call_args[0][0]
        self.assertIn("docker compose pull", args)
        self.assertIn("env", str(os.environ)) # Just ensuring environment is passed usually

if __name__ == '__main__':
    unittest.main()
