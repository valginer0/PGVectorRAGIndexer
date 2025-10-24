from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

import desktop_app.ui.source_open_manager as manager_module
from desktop_app.ui.source_open_manager import SourceOpenManager


class _StubApiClient:
    def __init__(self):
        self.uploaded = []
        self.fail = False

    def upload_document(self, file_path: Path, custom_source_uri: str = None, force_reindex: bool = False):
        if self.fail:
            raise RuntimeError("upload failed")
        self.uploaded.append((file_path, custom_source_uri, force_reindex))
        return {"status": "ok"}


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def manager(qt_app):
    parent = QWidget()
    api_client = _StubApiClient()
    manager = SourceOpenManager(api_client=api_client, parent=parent)
    manager._test_parent = parent  # keep Python reference alive
    manager._test_api_client = api_client
    return manager


def test_open_path_no_path_shows_warning(monkeypatch, manager):
    captured = {}

    def fake_warning(parent, title, text):
        captured["message"] = (title, text)
        return QMessageBox.Ok

    monkeypatch.setattr(manager_module.QMessageBox, "warning", fake_warning)

    manager.open_path("")

    assert captured["message"][0] == "No Path"


def test_open_path_missing_file(monkeypatch, manager, tmp_path):
    missing = tmp_path / "missing.txt"
    captured = {}

    def fake_warning(parent, title, text):
        captured["message"] = (title, text)
        return QMessageBox.Ok

    monkeypatch.setattr(manager_module.QMessageBox, "warning", fake_warning)

    manager.open_path(str(missing))

    assert "does not exist" in captured["message"][1]


def test_open_path_tracks_recents_and_auto_queues(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)

    manager.open_path(str(file_path))

    entries = manager.get_recent_entries()
    assert entries and entries[0].path == str(file_path)
    assert entries[0].queued is True


def test_open_path_can_skip_auto_queue(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)

    manager.open_path(str(file_path), auto_queue=False)

    entries = manager.get_recent_entries()
    assert entries[0].queued is False


def test_trigger_reindex_path_sets_reindexed(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)

    manager.open_path(str(file_path), auto_queue=False)

    manager.trigger_reindex_path(str(file_path))

    entry = manager.get_recent_entries()[0]
    assert len(manager._test_api_client.uploaded) == 1
    assert entry.reindexed is True
    assert entry.queued is False


def test_queue_entry_toggle(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    manager.open_path(str(file_path), auto_queue=False)

    entry = manager.queue_entry(str(file_path), True)
    assert entry and entry.queued is True

    entry = manager.queue_entry(str(file_path), False)
    assert entry and entry.queued is False


def test_process_queue_success(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    manager.open_path(str(file_path))

    success, failures = manager.process_queue()

    entry = manager.get_recent_entries()[0]
    assert (success, failures) == (1, 0)
    assert entry.reindexed is True
    assert entry.queued is False


def test_process_queue_handles_failures(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    manager.open_path(str(file_path))
    manager._test_api_client.fail = True

    success, failures = manager.process_queue()

    entry = manager.get_recent_entries()[0]
    assert (success, failures) == (0, 1)
    assert entry.queued is True
    assert entry.reindexed is False
    assert entry.last_error == "upload failed"


def test_remove_entry(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    manager.open_path(str(file_path), auto_queue=False)

    removed = manager.remove_entry(str(file_path))
    assert removed is True
    assert manager.get_recent_entries() == []
