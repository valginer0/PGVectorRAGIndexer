"""
Docker container management for the desktop application.
"""

import subprocess
import logging
import time
import platform
from typing import Optional, Tuple
from pathlib import Path
import os

logger = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker containers for the application."""
    
    def __init__(self, project_path: Path):
        """
        Initialize Docker manager.
        
        Args:
            project_path: Path to the project directory containing docker-compose.yml
        """
        self.project_path = project_path
        self.docker_compose_file = project_path / "docker-compose.yml"
        
        # Detect if running on Windows
        self.is_windows = platform.system() == "Windows"
        
        # Convert Windows path to WSL format for docker commands
        if self.is_windows:
            path_str = str(project_path)
            
            if path_str.startswith("\\\\wsl"):
                # Already a WSL path: \\wsl.localhost\Ubuntu\home\user\...
                # Convert to /home/user/...
                if "\\wsl.localhost\\Ubuntu\\" in path_str:
                    # Remove the \\wsl.localhost\Ubuntu\ prefix completely
                    wsl_part = path_str.replace("\\wsl.localhost\\Ubuntu\\", "")
                    # Convert backslashes and ensure single leading slash
                    self.wsl_project_path = "/" + wsl_part.replace("\\", "/").lstrip("/")
                else:
                    self.wsl_project_path = path_str.replace("\\", "/")
            else:
                # Windows path: C:\Users\... → /mnt/c/Users/...
                # Convert drive letter and backslashes
                if len(path_str) >= 2 and path_str[1] == ':':
                    drive = path_str[0].lower()
                    rest = path_str[2:].replace("\\", "/")
                    self.wsl_project_path = f"/mnt/{drive}{rest}"
                else:
                    self.wsl_project_path = path_str.replace("\\", "/")
        else:
            self.wsl_project_path = str(project_path)
        
    def _run_docker_command(self, cmd: list, **kwargs) -> subprocess.CompletedProcess:
        """
        Run a docker command, using WSL only for docker compose with path conversion.
        
        Args:
            cmd: Command list
            **kwargs: Additional arguments for subprocess.run
            
        Returns:
            CompletedProcess result
        """
        # Try to run docker directly first (works with Docker Desktop and Rancher Desktop on Windows)
        # Only use WSL for docker compose commands that need path conversion
        return subprocess.run(cmd, **kwargs)
    
    def is_docker_available(self) -> bool:
        """Check if Docker is installed and running."""
        try:
            result = self._run_docker_command(
                ["docker", "ps"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def get_container_status(self) -> Tuple[bool, bool]:
        """
        Get status of database and app containers.
        
        Returns:
            Tuple of (db_running, app_running)
        """
        try:
            result = self._run_docker_command(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.warning(f"Docker ps failed: {result.stderr}")
                return False, False
            
            containers = result.stdout.strip().split('\n')
            logger.debug(f"Found containers: {containers}")
            
            db_running = 'vector_rag_db' in containers
            app_running = 'vector_rag_app' in containers
            
            logger.debug(f"Container status - DB: {db_running}, App: {app_running}")
            return db_running, app_running
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout checking container status")
            return False, False
        except FileNotFoundError:
            logger.error("Docker command not found")
            return False, False
        except Exception as e:
            logger.error(f"Error checking container status: {e}")
            return False, False
    
    def check_daemon_connection(self) -> Tuple[bool, str]:
        """
        Check if we can actually talk to the Docker daemon.
        
        Returns:
            Tuple of (connected, error_message)
        """
        try:
            # Check for Docker info (requires active daemon)
            result = self._run_docker_command(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return True, ""
            
            # Diagnose specific Windows pipe error
            error_output = result.stderr or ""
            
            # "The system cannot find the file specified" = Daemon not listening on pipe
            if "system cannot find the file" in error_output:
                return False, "Container runtime is not running.\n\nPlease start Rancher Desktop (or Docker Desktop) and wait for it to initialize."
            
            # Only report privilege error if it's actually "Access is denied"
            if "Access is denied" in error_output:
                return False, "Permission denied connecting to Docker daemon.\n\nPlease ensure your user is in the 'docker-users' group."
            
            return False, f"Docker daemon is not responsive: {error_output}"
            
        except FileNotFoundError:
            return False, "Docker executable not found. Please install Docker Desktop or Rancher Desktop."
        except Exception as e:
            return False, f"Error checking Docker daemon: {str(e)}"

        except Exception as e:
            return False, f"Error checking Docker daemon: {str(e)}"

    def start_runtime(self) -> Tuple[bool, str]:
        """
        Attempt to start the container runtime (Rancher Desktop or Docker Desktop).
        Uses logic from legacy installer.ps1.
        """
        logger.info("Attempting to start container runtime...")
        
        # 1. Try rdctl (Rancher Desktop CLI)
        # Check standard Windows paths for rdctl first (as per installer.ps1)
        rdctl_path = "rdctl" # Default to PATH
        if self.is_windows:
            potential_rdctl = [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"),
            ]
            for path in potential_rdctl:
                if os.path.exists(path):
                    rdctl_path = path
                    break
        
        try:
            # 'rdctl start' starts the app in the background
            # Match legacy script behavior: explicitly set engine to moby (docker)
            cmd = [rdctl_path, "start", "--container-engine", "moby"]
            
            # Use DETACHED process if on Windows to avoid blocking
            if self.is_windows:
                 subprocess.Popen(
                    cmd,
                    close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, 'DETACHED_PROCESS') else 0x00000008, 
                    shell=False
                )
                 logger.info(f"Triggered Rancher Desktop start via {rdctl_path}")
                 return True, "Starting Rancher Desktop..."
            else:
                # Non-Windows fallback (e.g. Linux)
                result = self._run_docker_command(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                     return True, "Starting Rancher Desktop..."

        except FileNotFoundError:
             logger.debug(f"rdctl not found at {rdctl_path}")
        except Exception as e:
            logger.warning(f"Failed to run rdctl: {e}")

        # 2. Try locating executables directly (Windows Legacy Fallback)
        if self.is_windows:
            search_paths = [
                # Rancher Desktop Main Executable
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Rancher Desktop\Rancher Desktop.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Rancher Desktop\Rancher Desktop.exe"),
                # Docker Desktop
                os.path.expandvars(r"%PROGRAMFILES%\Docker\Docker\Docker Desktop.exe"),
            ]
            
            for exe_path in search_paths:
                if os.path.exists(exe_path):
                    try:
                        logger.info(f"Found runtime at {exe_path}, launching...")
                        # Use Popen to launch DETACHED so we don't block
                        subprocess.Popen(
                            [exe_path],
                            close_fds=True,
                            creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, 'DETACHED_PROCESS') else 0x00000008, 
                            shell=False
                        )
                        return True, f"Launching {Path(exe_path).stem}..."
                    except Exception as e:
                        logger.error(f"Failed to launch {exe_path}: {e}")
        
        return False, "Could not find Rancher Desktop or Docker Desktop executable."

    def pull_images(self) -> Tuple[bool, str]:
        """
        Pull latest Docker images from the registry.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info("Pulling latest Docker images...")
            result = subprocess.run(
                ["docker", "compose", "pull"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                logger.info("Images pulled successfully")
                return True, "Docker images updated successfully."
            else:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to pull images: {error_msg}")
                return False, f"Failed to pull images: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "Timeout pulling images"
        except Exception as e:
            logger.error(f"Error pulling images: {e}")
            return False, str(e)

    def start_containers(self, force_pull: bool = False) -> Tuple[bool, str]:
        """
        Start Docker containers using docker-compose.
        
        Args:
            force_pull: If True, run 'docker compose pull' before starting.
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # First, verify daemon connection
            connected, daemon_error = self.check_daemon_connection()
            
            if not connected:
                # If daemon is missing, try to start it automatically
                if "Container runtime is not running" in daemon_error:
                    logger.info("Daemon not running, attempting to start runtime...")
                    runtime_started, runtime_msg = self.start_runtime()
                    
                    if runtime_started:
                        # Wait for daemon to become ready
                        logger.info("Runtime launched, waiting for socket/pipe...")
                        daemon_ready = False
                        for i in range(20): # Wait up to 100s for backend to start
                            connected, _ = self.check_daemon_connection()
                            if connected:
                                daemon_ready = True
                                logger.info("Daemon connection established!")
                                break
                            time.sleep(5)
                            logger.info(f"Waiting for runtime... {(i+1)*5}s")
                        
                        if not daemon_ready:
                            return False, "Launched container runtime, but it is not responding yet.\n\nPlease wait for it to finish starting and try again."
                    else:
                        # Failed to auto-start
                        return False, "Container runtime is not running and could not be started automatically.\n\nPlease start Rancher Desktop manually."
                else:
                    return False, daemon_error

            # Optional: Pull latest images
            if force_pull:
                logger.info("Forcing image pull before start...")
                pull_success, pull_msg = self.pull_images()
                if not pull_success:
                    logger.warning(f"Forced pull failed: {pull_msg}. Attempting to start with local images.")

            # Check if containers are already running
            db_running, app_running = self.get_container_status()
            if db_running and app_running and not force_pull:
                logger.info("Containers are already running")
                return True, "Containers are already running and healthy!"
            
            logger.info("Starting Docker containers...")
            
            # If force_pull, we should recreate them to pick up new images
            cmd = ["docker", "compose", "up", "-d"]
            if force_pull:
                cmd.append("--force-recreate")
            
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                # Wait for containers to be healthy (with retries)
                logger.info("Waiting for containers to become healthy...")
                max_retries = 18  # 18 * 5 = 90 seconds max (API needs time to start)
                for i in range(max_retries):
                    time.sleep(5)
                    db_running, app_running = self.get_container_status()
                    
                    if db_running and app_running:
                        logger.info("Containers are running, waiting for API...")
                        # Give API a bit more time to be ready
                        if i >= 3:  # After 15+ seconds, containers should be stable
                            logger.info("Containers started successfully")
                            return True, "Containers started successfully!\n\nThe API should be ready shortly.\n\nIf the API status doesn't turn green, please wait another moment and click 'Refresh Status'."
                    
                    logger.info(f"Waiting... ({(i+1)*5}s)")
                
                # Final check
                db_running, app_running = self.get_container_status()
                if db_running and app_running:
                    return True, "Containers are running!\n\nThe API may still be initializing.\nPlease wait a moment and click 'Refresh Status' in the main window."
                elif db_running:
                    return True, "Database started. Application is still starting up.\n\nPlease wait a moment and click 'Refresh Status'."
                else:
                    return False, "Containers started but not healthy after 90 seconds.\n\nTry running: docker ps\nAnd check logs with: docker logs vector_rag_app"
            else:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to start containers: {error_msg}")
                # Re-check daemon just in case it crashed during start
                connected, daemon_err_retry = self.check_daemon_connection()
                if not connected:
                     return False, daemon_err_retry
                
                return False, f"Failed to start containers: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "Timeout starting containers"
        except FileNotFoundError:
            return False, "Docker not found. Please install Docker Desktop."
        except Exception as e:
            logger.error(f"Error starting containers: {e}")
            return False, str(e)
    
    def stop_containers(self) -> Tuple[bool, str]:
        """
        Stop Docker containers.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info("Stopping Docker containers...")
            
            # Use docker compose directly
            result = subprocess.run(
                ["docker", "compose", "down"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info("Containers stopped successfully")
                return True, "Containers stopped successfully"
            else:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to stop containers: {error_msg}")
                return False, f"Failed to stop containers: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, "Timeout stopping containers"
        except Exception as e:
            logger.error(f"Error stopping containers: {e}")
            return False, str(e)
    
    def restart_containers(self) -> Tuple[bool, str]:
        """
        Restart Docker containers.
        
        Returns:
            Tuple of (success, message)
        """
        success, msg = self.stop_containers()
        if not success:
            return False, f"Failed to stop: {msg}"
        
        time.sleep(2)
        return self.start_containers()
    
    def get_logs(self, container_name: str = "vector_rag_app", lines: int = 100) -> str:
        """
        Get logs from a container.
        
        Args:
            container_name: Name of the container
            lines: Number of lines to retrieve
            
        Returns:
            Log output as string
        """
        try:
            result = self._run_docker_command(
                ["docker", "logs", "--tail", str(lines), container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                return f"Error getting logs: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return "Timeout getting logs"
        except Exception as e:
            return f"Error: {e}"
