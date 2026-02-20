"""
Opt-in anonymous usage analytics for the desktop app.

Privacy-first design:
- Off by default (opt-in only)
- No PII, no document content, no file names, no search queries
- All events logged locally for full auditability
- Silent failure — never blocks UI or raises exceptions
"""

import json
import logging
import platform
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from . import app_config

logger = logging.getLogger(__name__)

# Maximum events kept in the local log file
_MAX_LOG_EVENTS = 500


def _log_path() -> Path:
    """Return the path to the local analytics event log."""
    return app_config._get_config_dir() / "analytics_log.jsonl"


def _get_or_create_install_id() -> str:
    """Return a stable anonymous install ID (created once, persisted)."""
    install_id = app_config.get("analytics_install_id")
    if not install_id:
        install_id = uuid.uuid4().hex
        app_config.set("analytics_install_id", install_id)
    return install_id


class AnalyticsClient:
    """Lightweight, opt-in analytics tracker.

    Events are always appended to a local JSONL log (for the user's
    audit viewer in Settings).  When enabled, they are also queued
    for batch transmission to the backend's ``/api/v1/activity``
    endpoint.
    """

    def __init__(self, app_version: str = ""):
        self._enabled: bool = app_config.get("analytics_enabled", False)
        self._app_version = app_version
        self._session_id = uuid.uuid4().hex[:12]
        self._install_id = _get_or_create_install_id()
        self._os_info = f"{platform.system()} {platform.release()}"
        self._python_version = platform.python_version()
        self._today_active_sent = False
        self._first_search_sent = bool(app_config.get("analytics_first_search"))
        self._first_upload_sent = bool(app_config.get("analytics_first_upload"))
        self._api_client = None  # set later via set_api_client()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        app_config.set("analytics_enabled", enabled)

    def set_api_client(self, api_client) -> None:
        """Provide the API client for optional server-side transmission."""
        self._api_client = api_client

    # ------------------------------------------------------------------
    # Core tracking
    # ------------------------------------------------------------------

    def track(self, event: str, properties: Optional[dict[str, Any]] = None) -> None:
        """Record an analytics event.

        The event is *always* written to the local audit log.
        If analytics is enabled, it is also sent to the backend.
        """
        record = {
            "event": event,
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "session": self._session_id,
            "install_id": self._install_id,
            "app_version": self._app_version,
            "os": self._os_info,
            "properties": properties or {},
        }
        self._append_log(record)

        if self._enabled:
            self._send(record)

    # ------------------------------------------------------------------
    # Convenience events
    # ------------------------------------------------------------------

    def track_app_started(self) -> None:
        self.track("app.started")

    def track_daily_active(self) -> None:
        """Send at most one daily-active event per session."""
        if self._today_active_sent:
            return
        self._today_active_sent = True
        self.track("app.daily_active", {"date": date.today().isoformat()})

    def track_search(self, result_count: int, duration_ms: int) -> None:
        self.track("search.completed", {
            "result_count": result_count,
            "duration_ms": duration_ms,
        })
        if not self._first_search_sent:
            self._first_search_sent = True
            app_config.set("analytics_first_search", True)
            self.track("milestone.first_search")

    def track_upload(self, file_count: int, success_count: int, duration_s: float) -> None:
        self.track("upload.completed", {
            "file_count": file_count,
            "success_count": success_count,
            "duration_s": round(duration_s, 1),
        })
        if not self._first_upload_sent:
            self._first_upload_sent = True
            app_config.set("analytics_first_upload", True)
            self.track("milestone.first_upload")

    def track_tab_opened(self, tab_name: str) -> None:
        self.track("tab.opened", {"tab": tab_name})

    def track_feature_used(self, feature: str) -> None:
        self.track("feature.used", {"feature": feature})

    def track_error(self, operation: str, error_type: str) -> None:
        self.track("error.occurred", {
            "operation": operation,
            "error_type": error_type,
        })

    # ------------------------------------------------------------------
    # Local audit log
    # ------------------------------------------------------------------

    def get_event_log(self, limit: int = 100) -> list[dict]:
        """Return the most recent events from the local log."""
        path = _log_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            events = []
            for line in lines[-limit:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return events
        except Exception:
            return []

    def clear_event_log(self) -> None:
        """Delete the local audit log."""
        try:
            path = _log_path()
            if path.exists():
                path.unlink()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_log(self, record: dict) -> None:
        """Append one event to the local JSONL log, rotating if too large."""
        try:
            path = _log_path()
            path.parent.mkdir(parents=True, exist_ok=True)

            # Rotate: keep only the last _MAX_LOG_EVENTS lines
            if path.exists():
                lines = path.read_text(encoding="utf-8").strip().splitlines()
                if len(lines) >= _MAX_LOG_EVENTS:
                    keep = lines[-((_MAX_LOG_EVENTS // 2)):]
                    path.write_text(
                        "\n".join(keep) + "\n", encoding="utf-8"
                    )

            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception as exc:
            logger.debug("analytics log write failed: %s", exc)

    def _send(self, record: dict) -> None:
        """Best-effort send to backend.  Never raises."""
        if not self._api_client:
            return
        try:
            self._api_client.post_activity(
                action=record["event"],
                client_id=self._install_id,
                details=record.get("properties"),
            )
        except Exception as exc:
            logger.debug("analytics send failed (non-blocking): %s", exc)
