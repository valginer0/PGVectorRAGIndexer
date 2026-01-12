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
        InstallStep(5, "Setting Up Application", "~3 minutes"),
        InstallStep(6, "Finalizing", "~30 seconds"),
    ]
    
    def __init__(self):
        self.is_running = False
        self.cancelled = False
        self._progress_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
    
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
            self._log("Docker installed but not running", "warning")
            self._log("Please start Docker Desktop or Rancher Desktop", "info")
            return True  # Continue anyway, user can start it later
        
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
    # Step 5: Setup Application
    # =========================================================================
    
    def _step_setup_application(self) -> bool:
        """Clone repo and setup application."""
        step = self.steps[4]
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
    # Step 6: Finalize
    # =========================================================================
    
    def _step_finalize(self) -> bool:
        """Create shortcuts and finalize installation."""
        step = self.steps[5]
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
    
    def run(self, progress_callback: Callable = None, log_callback: Callable = None) -> bool:
        """Run the full installation."""
        self.is_running = True
        self.cancelled = False
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        
        steps_functions = [
            self._step_check_system,
            self._step_install_python,
            self._step_install_git,
            self._step_install_docker,
            self._step_setup_application,
            self._step_finalize,
        ]
        
        try:
            for i, step_func in enumerate(steps_functions):
                if self.cancelled:
                    self._log("Installation cancelled by user", "warning")
                    return False
                
                success = step_func()
                if not success:
                    return False
            
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
