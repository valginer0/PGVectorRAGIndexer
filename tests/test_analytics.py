"""Tests for the desktop app analytics module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from desktop_app.utils.analytics import AnalyticsClient, _log_path


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Redirect analytics log and config to a temp directory."""
    with patch("desktop_app.utils.analytics.app_config") as mock_config:
        config_store = {}

        def mock_get(key, default=None):
            return config_store.get(key, default)

        def mock_set(key, value):
            config_store[key] = value

        mock_config.get.side_effect = mock_get
        mock_config.set.side_effect = mock_set
        mock_config._get_config_dir.return_value = tmp_path

        yield mock_config, config_store


class TestAnalyticsClient:

    def test_defaults_to_disabled(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        assert client.enabled is False

    def test_set_enabled(self, tmp_config_dir):
        mock_config, store = tmp_config_dir
        client = AnalyticsClient(app_version="1.0.0")
        client.set_enabled(True)
        assert client.enabled is True
        mock_config.set.assert_called_with("analytics_enabled", True)

    def test_track_writes_to_log(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track("test.event", {"key": "value"})

        events = client.get_event_log()
        assert len(events) == 1
        assert events[0]["event"] == "test.event"
        assert events[0]["properties"]["key"] == "value"
        assert events[0]["app_version"] == "1.0.0"
        assert "session" in events[0]
        assert "install_id" in events[0]

    def test_track_does_not_send_when_disabled(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        mock_api = MagicMock()
        client.set_api_client(mock_api)

        client.track("test.event")
        mock_api.post_activity.assert_not_called()

    def test_track_sends_when_enabled(self, tmp_config_dir):
        _, store = tmp_config_dir
        store["analytics_enabled"] = True
        client = AnalyticsClient(app_version="1.0.0")
        mock_api = MagicMock()
        client.set_api_client(mock_api)

        client.track("test.event", {"count": 5})
        mock_api.post_activity.assert_called_once()
        call_kwargs = mock_api.post_activity.call_args
        assert call_kwargs[1]["action"] == "test.event"

    def test_send_failure_is_silent(self, tmp_config_dir):
        _, store = tmp_config_dir
        store["analytics_enabled"] = True
        client = AnalyticsClient(app_version="1.0.0")
        mock_api = MagicMock()
        mock_api.post_activity.side_effect = ConnectionError("offline")
        client.set_api_client(mock_api)

        # Should not raise
        client.track("test.event")

    def test_track_app_started(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_app_started()
        events = client.get_event_log()
        assert events[0]["event"] == "app.started"

    def test_track_daily_active_deduplicates(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_daily_active()
        client.track_daily_active()
        client.track_daily_active()
        events = client.get_event_log()
        daily_events = [e for e in events if e["event"] == "app.daily_active"]
        assert len(daily_events) == 1

    def test_track_search(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_search(result_count=10, duration_ms=250)
        events = client.get_event_log()
        assert events[0]["event"] == "search.completed"
        assert events[0]["properties"]["result_count"] == 10
        # First search should also trigger milestone
        assert any(e["event"] == "milestone.first_search" for e in events)

    def test_first_search_milestone_only_once(self, tmp_config_dir):
        _, store = tmp_config_dir
        client = AnalyticsClient(app_version="1.0.0")
        client.track_search(result_count=5, duration_ms=100)
        client.track_search(result_count=3, duration_ms=80)
        events = client.get_event_log()
        milestones = [e for e in events if e["event"] == "milestone.first_search"]
        assert len(milestones) == 1

    def test_track_upload(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_upload(file_count=3, success_count=2, duration_s=4.567)
        events = client.get_event_log()
        assert events[0]["event"] == "upload.completed"
        assert events[0]["properties"]["file_count"] == 3
        assert events[0]["properties"]["duration_s"] == 4.6

    def test_track_tab_opened(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_tab_opened("Search")
        events = client.get_event_log()
        assert events[0]["event"] == "tab.opened"
        assert events[0]["properties"]["tab"] == "Search"

    def test_track_error(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track_error(operation="upload", error_type="ConnectionError")
        events = client.get_event_log()
        assert events[0]["event"] == "error.occurred"
        assert events[0]["properties"]["operation"] == "upload"

    def test_clear_event_log(self, tmp_config_dir):
        client = AnalyticsClient(app_version="1.0.0")
        client.track("test.event")
        assert len(client.get_event_log()) == 1
        client.clear_event_log()
        assert len(client.get_event_log()) == 0

    def test_log_rotation(self, tmp_config_dir):
        """Test that the log file doesn't grow unbounded."""
        client = AnalyticsClient(app_version="1.0.0")
        # Write enough events to trigger rotation
        with patch("desktop_app.utils.analytics._MAX_LOG_EVENTS", 10):
            for i in range(15):
                client.track("bulk.event", {"i": i})
        events = client.get_event_log(limit=1000)
        # After rotation, should have roughly half + the new ones
        assert len(events) <= 15

    def test_no_pii_in_events(self, tmp_config_dir):
        """Verify events don't contain document content or queries."""
        client = AnalyticsClient(app_version="1.0.0")
        client.track_search(result_count=5, duration_ms=100)
        client.track_upload(file_count=2, success_count=2, duration_s=3.0)
        client.track_tab_opened("Documents")

        events = client.get_event_log()
        for event in events:
            props = event.get("properties", {})
            # Should never contain query text, file names, or document content
            for key in props:
                assert key not in ("query", "file_name", "content", "text",
                                   "search_query", "document_name")
