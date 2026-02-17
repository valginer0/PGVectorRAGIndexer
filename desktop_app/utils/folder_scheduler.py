"""
In-app QTimer-based scheduler for watched folders (#6).

Periodically checks which watched folders are due for a scan based on
their cron schedule and triggers scans via the API client.  This is the
fallback scheduler that runs inside the desktop app process — no external
service (systemd/launchd) required.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

# Default check interval: every 60 seconds
_DEFAULT_CHECK_INTERVAL_MS = 60_000


def _cron_is_due(cron_expr: str, last_scanned_at: Optional[str]) -> bool:
    """Check whether a cron expression is due for execution.

    Supports a simplified subset of cron:
        - ``*/N`` in the hours field  → every N hours
        - ``0 0 * * *``              → daily at midnight
        - ``0 */6 * * *``            → every 6 hours

    If *last_scanned_at* is None the folder has never been scanned and is
    always considered due.

    For a full cron parser, consider the ``croniter`` package.  This
    lightweight implementation covers the most common scheduling patterns
    without adding a dependency.
    """
    if last_scanned_at is None:
        return True

    try:
        if isinstance(last_scanned_at, str):
            # Handle ISO format with or without timezone
            last_dt = datetime.fromisoformat(last_scanned_at.replace("Z", "+00:00"))
        else:
            last_dt = last_scanned_at

        # Ensure timezone-aware
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        elapsed_hours = (now - last_dt).total_seconds() / 3600.0

        parts = cron_expr.strip().split()
        if len(parts) < 5:
            logger.warning("Invalid cron expression: %s", cron_expr)
            return False

        _minute, hour_field, _dom, _month, _dow = parts[:5]

        # Parse hour field for interval
        if hour_field.startswith("*/"):
            try:
                interval_hours = int(hour_field[2:])
                return elapsed_hours >= interval_hours
            except ValueError:
                pass

        # Exact hour match (e.g. "0 0 * * *" = daily at midnight)
        if hour_field.isdigit():
            # Due if more than 24 hours since last scan
            return elapsed_hours >= 24.0

        # Wildcard = every hour
        if hour_field == "*":
            return elapsed_hours >= 1.0

        return False
    except Exception as e:
        logger.warning("Error parsing cron/last_scanned: %s", e)
        return False


class FolderScheduler(QObject):
    """Periodically checks watched folders and triggers scans when due.

    Signals:
        scan_started(str, str): Emitted when a scan starts (folder_id, folder_path).
        scan_completed(str, dict): Emitted when a scan finishes (folder_id, result).
        scan_failed(str, str): Emitted on scan error (folder_id, error_message).
    """

    scan_started = Signal(str, str)
    scan_completed = Signal(str, dict)
    scan_failed = Signal(str, str)

    def __init__(
        self,
        api_client,
        check_interval_ms: int = _DEFAULT_CHECK_INTERVAL_MS,
        parent=None,
    ):
        super().__init__(parent)
        self._api_client = api_client
        self._client_id: Optional[str] = None
        self._running = False

        self._timer = QTimer(self)
        self._timer.setInterval(check_interval_ms)
        self._timer.timeout.connect(self._check_folders)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def set_client_id(self, client_id: str):
        """Set the client_id to attribute scans to."""
        self._client_id = client_id

    def start(self):
        """Start the scheduler."""
        if self._running:
            return
        self._running = True
        self._timer.start()
        logger.info("Folder scheduler started (interval=%dms)", self._timer.interval())

    def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        logger.info("Folder scheduler stopped")

    def check_now(self):
        """Trigger an immediate check (useful after adding a folder)."""
        self._check_folders()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_folders(self):
        """Fetch enabled folders and scan any that are due.

        #6b: Only scans client-scope roots owned by this client.
        Skips server-scope roots and roots owned by other clients.
        """
        try:
            data = self._api_client.list_watched_folders(enabled_only=True)
            folders = data.get("folders", [])
        except Exception as e:
            logger.warning("Scheduler: failed to list folders: %s", e)
            return

        for folder in folders:
            # #6b scope filtering: skip non-client roots
            scope = folder.get("execution_scope", "client")
            if scope != "client":
                continue

            # #6b executor filtering: skip roots owned by other clients
            executor = folder.get("executor_id")
            if executor and self._client_id and executor != self._client_id:
                continue

            folder_id = folder.get("id")
            folder_path = folder.get("folder_path", "")
            cron = folder.get("schedule_cron", "0 */6 * * *")
            last_scanned = folder.get("last_scanned_at")

            if _cron_is_due(cron, last_scanned):
                self._trigger_scan(folder_id, folder_path)

    def _trigger_scan(self, folder_id: str, folder_path: str):
        """Trigger a scan for a single folder."""
        try:
            self.scan_started.emit(folder_id, folder_path)
            logger.info("Scheduler: scanning %s", folder_path)
            result = self._api_client.scan_watched_folder(
                folder_id, client_id=self._client_id
            )
            self.scan_completed.emit(folder_id, result)
            logger.info(
                "Scheduler: scan complete for %s — %s",
                folder_path,
                result.get("status", "unknown"),
            )
        except Exception as e:
            error_msg = str(e)
            self.scan_failed.emit(folder_id, error_msg)
            logger.warning("Scheduler: scan failed for %s: %s", folder_path, e)
