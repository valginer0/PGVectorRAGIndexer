"""
PGVectorRAGIndexer Windows Installer - Logic
Contains all installation functions: prerequisite checking, downloads, setup.
"""

import os
import sys
import subprocess
import shutil
import urllib.request
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional, List
from pathlib import Path


@dataclass
class InstallStep:
    """Represents an installation step."""
    number: int
    name: str
    time_estimate: str


class Installer:
    """Main installer logic."""
    
    INSTALL_DIR = os.path.join(os.environ.get('USERPROFILE', ''), 'PGVectorRAGIndexer')
    GITHUB_REPO = "valginer0/PGVectorRAGIndexer"
    
    steps = [
        InstallStep(1, "Checking System", "~10 seconds"),
        InstallStep(2, "Installing Python", "~2 minutes"),
        InstallStep(3, "Installing Git", "~1 minute"),
        InstallStep(4, "Installing Docker", "~3 minutes"),
        InstallStep(5, "Starting Container Runtime", "~2 minutes"),
        InstallStep(6, "Setting Up Application", "~3 minutes"),
        InstallStep(7, "Pulling Docker Images", "~3 minutes"),
        InstallStep(8, "Finalizing", "~30 seconds"),
    ]
    
    def __init__(self, install_dir: Optional[str] = None):
        if install_dir:
            self.INSTALL_DIR = install_dir
        
        # Ensure install dir exists or parent exists
        try:
            os.makedirs(self.INSTALL_DIR, exist_ok=True)
        except:
            pass
            
        self.is_running = False
        self.cancelled = False
        self._progress_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
        
        # State persistence file
        self.state_file = os.path.join(self.INSTALL_DIR, "install_state.json")
        self.reboot_required = False
    
    def cancel(self):
        """Cancel the installation."""
        self.cancelled = True
    
    def _log(self, message: str, level: str = "info"):
        """Log a message."""
        if self._log_callback:
            self._log_callback(message, level)
    
    def _update_progress(self, step: InstallStep, status: str):
        """Update progress."""
        if self._progress_callback:
            self._progress_callback(step, status)
    
    def _run_command(self, cmd: str, shell: bool = True) -> tuple:
        """Run a command and return (success, output)."""
        try:
            result = subprocess.run(
                cmd,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def _check_command(self, cmd: str) -> bool:
        """Check if a command exists."""
        try:
            result = subprocess.run(
                f"where {cmd}",
                shell=True,
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except:
            return False
    
    def _check_winget(self) -> bool:
        """Check if winget is available."""
        return self._check_command("winget")
    
    def _install_with_winget(self, package_id: str, name: str) -> bool:
        """Install a package with winget."""
        self._log(f"Installing {name}...")
        
        cmd = f'winget install {package_id} --silent --accept-package-agreements --accept-source-agreements'
        success, output = self._run_command(cmd)
        
        if success or "already installed" in output.lower():
            self._log(f"{name} installed successfully", "success")
            return True
        else:
            self._log(f"Failed to install {name}", "error")
            return False
    
    def _refresh_path(self):
        """Refresh PATH environment variable."""
        # Get updated PATH from registry
        try:
            import winreg
            
            # User PATH
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                               r"Environment", 0, winreg.KEY_READ) as key:
                user_path, _ = winreg.QueryValueEx(key, "Path")
            
            # System PATH  
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                               0, winreg.KEY_READ) as key:
                system_path, _ = winreg.QueryValueEx(key, "Path")
            
            os.environ['PATH'] = f"{user_path};{system_path}"
        except Exception as e:
            self._log(f"Could not refresh PATH: {e}", "warning")

    # =========================================================================
    # State Management & Reboot Handling
    # =========================================================================

    def _save_state(self, stage: str):
        """Save installation state to JSON."""
        state = {
            "Stage": stage,
            "InstallDir": self.INSTALL_DIR,
            "Timestamp": time.time()
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            self._log(f"Failed to save state: {e}", "warning")

    def _load_state(self) -> dict:
        """Load installation state."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _clear_state(self):
        """Clear state and remove scheduled task."""
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
            except:
                pass
        
        # Remove scheduled task
        subprocess.run(
            'schtasks /delete /tn "PGVectorRAGIndexer_Resume" /f',
            shell=True,
            capture_output=True
        )

    def request_reboot(self):
        """Register resume task and signal reboot requirement."""
        self._log("Scheduling resume after reboot...", "info")
        
        # 1. Save state
        self._save_state("PostReboot")
        
        # 2. Register Scheduled Task (Legacy Parity)
        # We need to find where the current python/installer is running from
        # If running from compiled .exe, sys.executable is the exe.
        # If running from script, it's python.exe
        
        executable = sys.executable
        script_args = ""
        
        if not getattr(sys, 'frozen', False):
            # We are running as script
            script_path = os.path.abspath(sys.argv[0])
            executable = sys.executable
            # We assume we are in venv or global python
            script_args = f'"{script_path}"'
        
        # Construct command: Run the installer with --resume flag (handled by GUI wrapper logic mostly, 
        # but logic class just prepares the environment)
        # Actually, the legacy script used arguments.
        # Here, we just want to run the installer executable again.
        
        cmd = f'"{executable}" {script_args}'
        
        # Create scheduled task "PGVectorRAGIndexer_Resume"
        # /sc onlogon /rl highest (if admin) - but installer might be user mode.
        # Legacy used Register-ScheduledTask. schtasks is the cli equivalent.
        
        schtasks_cmd = (
            f'schtasks /create /tn "PGVectorRAGIndexer_Resume" '
            f'/tr "\'{executable}\' {script_args}" '
            f'/sc onlogon /f'
        )
        
        res = subprocess.run(schtasks_cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            self._log(f"Warning: Could not schedule resume task: {res.stderr}", "warning")
            # Fallback: Registry Run key (User scope)
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "PGVectorRAGIndexer_Resume", 0, winreg.REG_SZ, cmd)
                winreg.CloseKey(key)
                self._log("Added to Registry Run key instad.", "info")
            except Exception as e:
                self._log(f"Failed to set registry run key: {e}", "error")

        self.reboot_required = True

    def _start_runtime_helper(self) -> bool:
        """
        Helper to start Rancher Desktop or Docker Desktop.
        Ported from parity with legacy installer.ps1
        """
        # 1. Try rdctl (Rancher Desktop CLI)
        rdctl_path = "rdctl" # Default to PATH
        
        # Check standard Windows paths (installer.ps1 logic)
        potential_rdctl = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
        ]
        for path in potential_rdctl:
            if os.path.exists(path):
                rdctl_path = path
                break
        
        try:
            # Match legacy script behavior: explicitly set engine to moby
            self._log(f"Attempting to start Rancher Desktop via {rdctl_path}...")
            # Use Popen to launch DETACHED so we don't block main thread forever
            # But we need to use 'start' command
            cmd = f'"{rdctl_path}" start --container-engine moby'
            subprocess.Popen(
                cmd, 
                shell=True,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, 'DETACHED_PROCESS') else 0x00000008
            )
            return True
        except Exception as e:
            self._log(f"Failed to run rdctl: {e}", "warning")

        # 2. Try locating executables directly (Windows Legacy Fallback)
        search_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Rancher Desktop\Rancher Desktop.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Rancher Desktop\Rancher Desktop.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Docker\Docker\Docker Desktop.exe"),
        ]
        
        for exe_path in search_paths:
            if os.path.exists(exe_path):
                try:
                    self._log(f"Found runtime at {exe_path}, launching...")
                    subprocess.Popen(
                        f'"{exe_path}"',
                        shell=True,
                        creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, 'DETACHED_PROCESS') else 0x00000008
                    )
                    return True
                except Exception as e:
                    self._log(f"Failed to launch {exe_path}: {e}", "error")
        
        return False
    
    # =========================================================================
    # Step 1: Check System
    # =========================================================================
    
    def _step_check_system(self) -> bool:
        """Check system requirements."""
        step = self.steps[0]
        self._update_progress(step, "Checking system requirements...")
        
        # Check Windows version
        import platform
        version = platform.version()
        self._log(f"Windows version: {version}")
        
        # Check if winget is available
        if not self._check_winget():
            self._log("winget not found - some installations may require manual setup", "warning")
        else:
            self._log("winget available", "success")
        
        # Check available disk space
        try:
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(os.environ.get('USERPROFILE', 'C:\\')),
                None, None, ctypes.pointer(free_bytes)
            )
            free_gb = free_bytes.value / (1024**3)
            self._log(f"Free disk space: {free_gb:.1f} GB")
            
            if free_gb < 5:
                self._log("Warning: Less than 5GB free space", "warning")
        except:
            pass
        
        return True
    
    # =========================================================================
    # Step 2: Install Python
    # =========================================================================
    
    def _step_install_python(self) -> bool:
        """Check/install Python."""
        step = self.steps[1]
        self._update_progress(step, "Checking Python installation...")
        
        # Check if Python is already installed
        if self._check_command("python"):
            success, output = self._run_command("python --version")
            if success:
                self._log(f"Python already installed: {output.strip()}", "success")
                return True
        
        # Install Python via winget
        if self._check_winget():
            self._update_progress(step, "Installing Python 3.11...")
            if self._install_with_winget("Python.Python.3.11", "Python 3.11"):
                self._refresh_path()
                return True
        
        self._log("Please install Python manually from python.org", "error")
        return False
    
    # =========================================================================
    # Step 3: Install Git
    # =========================================================================
    
    def _step_install_git(self) -> bool:
        """Check/install Git."""
        step = self.steps[2]
        self._update_progress(step, "Checking Git installation...")
        
        # Check if Git is already installed
        if self._check_command("git"):
            success, output = self._run_command("git --version")
            if success:
                self._log(f"Git already installed: {output.strip()}", "success")
                return True
        
        # Install Git via winget (user scope to avoid admin)
        if self._check_winget():
            self._update_progress(step, "Installing Git...")
            if self._install_with_winget("Git.Git --scope user", "Git"):
                self._refresh_path()
                return True
        
        self._log("Please install Git manually from git-scm.com", "error")
        return False
    
    # =========================================================================
    # Step 4: Install Docker
    # =========================================================================
    
    def _step_install_docker(self) -> bool:
        """Check/install Docker (Rancher Desktop)."""
        step = self.steps[3]
        self._update_progress(step, "Checking Docker installation...")
        
        # Check if Docker is already running
        success, _ = self._run_command("docker ps")
        if success:
            self._log("Docker is already running", "success")
            return True
        
        # Check if docker command exists but not running
        if self._check_command("docker"):
            self._log("Docker installed (service not active)", "warning")
            self._log("Runtime will be started automatically in the next step.", "info")
            return True  # Continue, Step 5 will start it
        
        # Check for Rancher Desktop binary directly (parity with legacy)
        rdctl_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
        ]
        for path in rdctl_paths:
            if os.path.exists(path):
                self._log(f"Rancher Desktop found at {path}", "success")
                return True
        
        # Install Rancher Desktop via winget
        if self._check_winget():
            self._update_progress(step, "Installing Rancher Desktop (Docker)...")
            if self._install_with_winget("suse.RancherDesktop", "Rancher Desktop"):
                self._log("Rancher Desktop installed - may need restart", "success")
                self._log("Please start Rancher Desktop after installation", "info")
                return True
        
        self._log("Please install Docker Desktop manually", "warning")
        return True  # Continue anyway
    
    # =========================================================================
    # Step 5: Start Container Runtime
    # =========================================================================
    
    def _step_start_runtime(self) -> bool:
        """Start Docker/Rancher Desktop."""
        step = self.steps[4]
        self._update_progress(step, "Starting container runtime...")
        
        # Check if already running
        success, _ = self._run_command("docker ps")
        if success:
            self._log("Container runtime already active", "success")
            return True
            
        # Attempt to start
        if self._start_runtime_helper():
            self._update_progress(step, "Waiting for Docker to initialize...")
            
            # Wait up to 300 seconds (parity with legacy)
            start_time = time.time()
            while time.time() - start_time < 300:
                success, _ = self._run_command("docker ps")
                if success:
                    self._log("Docker is ready!", "success")
                    return True
                time.sleep(5)
            
            self._log("Docker failed to become ready in time", "error")
            self._log("Taking too long? A system restart might fix this.", "warning")
            self.request_reboot()
            return False
        else:
            # Runtime start failed -> Likely needs reboot (fresh install of Rancher)
            self._log("Could not start container runtime automatically.", "warning")
            self._log("A system restart is required to complete Docker setup.", "warning")
            self.request_reboot()
            return False

    # =========================================================================
    # Step 6: Setup Application
    # =========================================================================
    
    def _step_setup_application(self) -> bool:
        """Clone repo and setup application."""
        step = self.steps[5]
        self._update_progress(step, "Setting up application...")
        
        # Clone or update repository
        if os.path.exists(os.path.join(self.INSTALL_DIR, '.git')):
            self._log("Updating existing installation...")
            os.chdir(self.INSTALL_DIR)
            self._run_command("git reset --hard HEAD")
            success, _ = self._run_command("git pull origin main")
        else:
            if os.path.exists(self.INSTALL_DIR):
                self._log("Removing incomplete installation...")
                shutil.rmtree(self.INSTALL_DIR, ignore_errors=True)
            
            self._log("Cloning repository...")
            success, output = self._run_command(
                f'git clone https://github.com/{self.GITHUB_REPO}.git "{self.INSTALL_DIR}"'
            )
        
        if not os.path.exists(self.INSTALL_DIR):
            self._log("Failed to clone repository", "error")
            return False
        
        self._log("Repository ready", "success")
        os.chdir(self.INSTALL_DIR)
        
        # Create virtual environment
        venv_dir = os.path.join(self.INSTALL_DIR, "venv-windows")
        if not os.path.exists(venv_dir):
            self._update_progress(step, "Creating virtual environment...")
            success, _ = self._run_command(f"python -m venv venv-windows")
            if not success:
                self._log("Failed to create virtual environment", "error")
                return False
        
        self._log("Virtual environment ready", "success")
        
        # Install dependencies
        self._update_progress(step, "Installing Python dependencies...")
        pip_path = os.path.join(venv_dir, "Scripts", "pip.exe")
        success, _ = self._run_command(f'"{pip_path}" install -q -r requirements-desktop.txt')
        
        if not success:
            self._log("Warning: Some dependencies may have failed", "warning")
        else:
            self._log("Dependencies installed", "success")
        
        return True

    # =========================================================================
    # Step 7: Pull Docker Images
    # =========================================================================

    def _step_pull_images(self) -> bool:
        """Pull Docker images (Parity with manage.ps1 update)."""
        step = self.steps[6]
        self._update_progress(step, "Pulling Docker images...")
        
        os.chdir(self.INSTALL_DIR)
        
        # Run docker compose pull
        # Use simple environment variable setup if needed, but default .env should handle it
        # or we just rely on default
        
        # Create temporary .env for image if needed, similar to manage.ps1
        # For simplicity/parity, we assume default image unless channel specified
        # Since we clone main, we use prod image mostly.
        
        env = os.environ.copy()
        env["APP_IMAGE"] = "ghcr.io/valginer0/pgvectorragindexer:latest"
        
        self._log("Pulling images (this may take a few minutes)...")
        success, output = self._run_command("docker compose pull", shell=True)
        
        if success:
            self._log("Images pulled successfully", "success")
            return True
        else:
            self._log(f"Failed to pull images: {output}", "warning")
            return True # Non-fatal, app will try to pull on run

    # =========================================================================
    # Step 8: Finalize
    # =========================================================================
    
    def _step_finalize(self) -> bool:
        """Create shortcuts and finalize installation."""
        step = self.steps[7]
        self._update_progress(step, "Creating desktop shortcut...")
        
        # Create desktop shortcut
        try:
            self._create_shortcut()
            self._log("Desktop shortcut created", "success")
        except Exception as e:
            self._log(f"Could not create shortcut: {e}", "warning")
        
        self._log("Installation complete!", "success")
        return True
    
    def _create_shortcut(self):
        """Create a desktop shortcut."""
        try:
            import winreg
            from pathlib import Path
            
            desktop = Path.home() / "Desktop"
            if not desktop.exists():
                # Try OneDrive Desktop
                desktop = Path.home() / "OneDrive" / "Desktop"
            
            shortcut_path = desktop / "PGVectorRAGIndexer.lnk"
            target = os.path.join(self.INSTALL_DIR, "run_desktop_app.bat")
            
            # Use PowerShell to create shortcut
            ps_command = f'''
            $WshShell = New-Object -comObject WScript.Shell
            $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
            $Shortcut.TargetPath = "{target}"
            $Shortcut.WorkingDirectory = "{self.INSTALL_DIR}"
            $Shortcut.Description = "PGVectorRAGIndexer - Semantic Document Search"
            $Shortcut.Save()
            '''
            
            subprocess.run(
                ["powershell", "-Command", ps_command],
                capture_output=True,
                timeout=30
            )
        except Exception as e:
            raise e
    
    # =========================================================================
    # Main Run
    # =========================================================================
    
    # =========================================================================
    # Main Run
    # =========================================================================
    
    def run(self, progress_callback: Callable = None, log_callback: Callable = None) -> bool:
        """Run the full installation."""
        self.is_running = True
        self.cancelled = False
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        
        # Define full sequence of steps
        steps_functions = [
            self._step_check_system,       # Step 1
            self._step_install_python,     # Step 2
            self._step_install_git,        # Step 3
            self._step_install_docker,     # Step 4 (Install binaries)
            self._step_start_runtime,      # Step 5 (Start & Wait)
            self._step_setup_application,  # Step 6
            self._step_pull_images,        # Step 7
            self._step_finalize,           # Step 8
        ]
        
        # Check for resume state
        state = self._load_state()
        start_index = 0
        
        if state and state.get("Stage") == "PostReboot":
            self._log("Resuming installation after restart...", "success")
            # Resume from Step 5 (Start Runtime) because that's what we rebooted for
            # Prereqs (1-4) are assumed done.
            start_index = 4 
            # Clear state now that we've resumed (or clear after success? Legacy cleared at end)
            # We'll clear at end to be safe.
        
        try:
            for i, step_func in enumerate(steps_functions):
                if i < start_index:
                    continue
                    
                if self.cancelled:
                    self._log("Installation cancelled by user", "warning")
                    return False
                
                # Check if reboot was requested by previous step
                if self.reboot_required:
                    # GUI will handle the actual dialog/exit
                    # We just stop processing steps here
                    return True 
                
                success = step_func()
                if not success:
                    # If step failed because it requested reboot, that's handled above next loop
                    if self.reboot_required:
                        return True
                    return False
            
            # If we got here, all steps finished
            self._clear_state()
            return True
            
        except Exception as e:
            self._log(f"Unexpected error: {e}", "error")
            return False
        finally:
            self.is_running = False
    
    def launch_app(self):
        """Launch the installed application."""
        run_script = os.path.join(self.INSTALL_DIR, "run_desktop_app.bat")
        if os.path.exists(run_script):
            subprocess.Popen(
                run_script,
                shell=True,
                cwd=self.INSTALL_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            # Fallback: run directly
            python_path = os.path.join(self.INSTALL_DIR, "venv-windows", "Scripts", "python.exe")
            subprocess.Popen(
                [python_path, "-m", "desktop_app.main"],
                cwd=self.INSTALL_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
