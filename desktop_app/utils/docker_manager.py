"""
Docker container management for the desktop application.
"""

import subprocess
import logging
import time
import platform
from typing import Optional, Tuple
from pathlib import Path

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
        Run a docker command, using WSL if on Windows.
        
        Args:
            cmd: Command list
            **kwargs: Additional arguments for subprocess.run
            
        Returns:
            CompletedProcess result
        """
        if self.is_windows:
            # Run docker through WSL
            wsl_cmd = ["wsl", "-d", "Ubuntu", "-e"] + cmd
            return subprocess.run(wsl_cmd, **kwargs)
        else:
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
                return False, False
            
            containers = result.stdout.strip().split('\n')
            db_running = 'vector_rag_db' in containers
            app_running = 'vector_rag_app' in containers
            
            return db_running, app_running
            
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False, False
    
    def start_containers(self) -> Tuple[bool, str]:
        """
        Start Docker containers using docker-compose.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info("Starting Docker containers...")
            
            if self.is_windows:
                # Run docker compose through WSL with cd to project directory
                result = subprocess.run(
                    ["wsl", "-d", "Ubuntu", "-e", "bash", "-c", 
                     f"cd {self.wsl_project_path} && docker compose up -d"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
            else:
                result = subprocess.run(
                    ["docker", "compose", "up", "-d"],
                    cwd=str(self.project_path),
                    capture_output=True,
                    text=True,
                    timeout=120
                )
            
            if result.returncode == 0:
                # Wait for containers to be healthy
                time.sleep(5)
                db_running, app_running = self.get_container_status()
                
                if db_running and app_running:
                    logger.info("Containers started successfully")
                    return True, "Containers started successfully"
                else:
                    return False, "Containers started but not healthy"
            else:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to start containers: {error_msg}")
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
            
            if self.is_windows:
                result = subprocess.run(
                    ["wsl", "-d", "Ubuntu", "-e", "bash", "-c",
                     f"cd {self.wsl_project_path} && docker compose down"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
            else:
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
