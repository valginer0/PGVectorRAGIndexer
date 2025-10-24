from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

import desktop_app.ui.source_open_manager as manager_module
from desktop_app.ui.source_open_manager import SourceOpenManager


class _StubApiClient:
    def __init__(self):
        self.uploaded = []
        self.upload_document_called = False

    def upload_document(self, file_path: Path, custom_source_uri: str = None, force_reindex: bool = False):
        self.uploaded.append((file_path, custom_source_uri, force_reindex))
        self.upload_document_called = True
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


def test_open_path_tracks_recents(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)

    manager.open_path(str(file_path), prompt_reindex=False)

    entries = manager.get_recent_entries()
    assert entries and entries[0].path == str(file_path)


def test_open_path_prompt_yes_triggers_reindex(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    monkeypatch.setattr(manager_module.QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(manager_module.QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(manager_module.QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    manager.open_path(str(file_path))

    entries = manager.get_recent_entries()
    assert entries[0].reindexed is True
    assert len(manager._test_api_client.uploaded) == 1


def test_open_path_prompt_no_skips_reindex(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    monkeypatch.setattr(manager_module.QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    monkeypatch.setattr(manager_module.QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(manager_module.QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    manager.open_path(str(file_path))

    assert len(manager._test_api_client.uploaded) == 0


def test_trigger_reindex_path_runs_without_prompt(monkeypatch, manager, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")

    monkeypatch.setattr(manager, "_launch_default", lambda path: None)
    monkeypatch.setattr(manager_module.QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    monkeypatch.setattr(manager_module.QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(manager_module.QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    manager.open_path(str(file_path), prompt_reindex=False)

    manager.trigger_reindex_path(str(file_path))

    assert len(manager._test_api_client.uploaded) == 1
