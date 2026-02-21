import time
import logging
from PySide6.QtCore import QThread, Signal
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HealthCheckWorker(QThread):
    """
    Background worker for periodic API health and Docker status checks.
    Decouples status polling from the main UI thread to prevent freezes.
    """
    # Result contains: health (dict), db_running (bool), app_running (bool), timestamp (float)
    status_updated = Signal(dict)

    def __init__(self, api_client, docker_manager, remote_mode=False, interval_ms=3000):
        super().__init__()
        self.api_client = api_client
        self.docker_manager = docker_manager
        self.remote_mode = remote_mode
        self.interval_ms = interval_ms
        self._running = True

    def stop(self):
        """Request the worker to stop."""
        self._running = False

    def run(self):
        """Continuous polling loop."""
        logger.debug("HealthCheckWorker started (remote=%s)", self.remote_mode)
        while self._running:
            try:
                # Docker status
                if self.remote_mode:
                    db_running, app_running = None, None
                else:
                    db_running, app_running = self.docker_manager.get_container_status()
                
                # API health
                health = self.api_client.get_health()
                
                # Emit result
                self.status_updated.emit({
                    "health": health,
                    "db_running": db_running,
                    "app_running": app_running,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"HealthCheckWorker error: {e}")
                self.status_updated.emit({
                    "health": {"status": "unhealthy", "error": str(e)},
                    "db_running": None if self.remote_mode else False,
                    "app_running": None if self.remote_mode else False,
                    "timestamp": time.time()
                })

            self.msleep(self.interval_ms)
        logger.debug("HealthCheckWorker stopped")
