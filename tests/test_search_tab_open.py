import os
import sys
import subprocess
from pathlib import Path

import pytest

# Mark all tests in this file as slow (UI tests with QApplication)
pytestmark = pytest.mark.slow
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt, QPoint

import desktop_app.ui.search_tab as search_tab_module
from desktop_app.ui.search_tab import SearchTab


class _DummyApiClient:
    def search(self, *args, **kwargs):
        return []

    def is_api_available(self):
        return True

    def get_metadata_values(self, key):
        if key == "type":
            return ["report", "policy"]
        return []


class _StubManager:
    def __init__(self, queued: bool = False):
        self.calls = []
        self._queued = queued

    def open_path(self, path: str, mode: str = "default", auto_queue: bool = True):
        self.calls.append(("open", mode, auto_queue, path))

    def trigger_reindex_path(self, path: str):
        self.calls.append(("reindex", path))
        return True

    def queue_entry(self, path: str, queued: bool):
        self.calls.append(("queue", path, queued))
        self._queued = queued
        return SimpleNamespace(path=path, queued=queued)

    def remove_entry(self, path: str) -> bool:
        self.calls.append(("remove", path))
        return True

    def find_entry(self, path: str):
        return SimpleNamespace(path=path, queued=self._queued)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def search_tab(qt_app):
    return SearchTab(_DummyApiClient())


@pytest.fixture
def search_tab_with_manager(qt_app):
    manager = _StubManager()
    tab = SearchTab(_DummyApiClient(), source_manager=manager)
    return tab, manager


def test_document_type_filter_populates_on_init(search_tab):
    assert search_tab.type_filter.count() >= 1
    assert search_tab.type_filter.findText("report") >= 0


def test_document_type_filter_includes_selection_in_search(monkeypatch, search_tab):
    captured = {}

    def fake_search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(search_tab.api_client, "search", fake_search)
    monkeypatch.setattr(search_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(search_tab_module.QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(search_tab_module.SearchWorker, "start", lambda self: self.run())

    search_tab.api_client.is_api_available = lambda: True
    search_tab.type_filter.setCurrentText("policy")
    search_tab.query_input.setText("security policy")
    search_tab.perform_search()

    assert captured.get("document_type") == "policy"


def test_display_results_uses_relevance_score(search_tab):
    results = [{
        "relevance_score": 0.87654,
        "source_uri": "/tmp/doc.txt",
        "chunk_index": 2,
        "text_content": "example"
    }]

    search_tab.display_results(results)

    score_item = search_tab.results_table.item(0, 0)
    chunk_item = search_tab.results_table.item(0, 2)

    assert score_item.text() == "0.8765"
    assert chunk_item.text() == "2"


def test_open_source_path_no_path_shows_warning(monkeypatch, search_tab):
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(search_tab_module.QMessageBox, "warning", fake_warning)
    search_tab.open_source_path("")
    assert captured


def test_open_source_path_missing_file(monkeypatch, search_tab, tmp_path):
    missing_path = tmp_path / "missing.txt"
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(search_tab_module.QMessageBox, "warning", fake_warning)
    search_tab.open_source_path(str(missing_path))
    assert captured


def test_open_source_path_windows(monkeypatch, search_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(search_tab_module.sys, "platform", "win32")

    def fake_startfile(path):
        called["path"] = path

    monkeypatch.setattr(search_tab_module.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(search_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    search_tab.open_source_path(str(file_path))
    assert called["path"] == str(file_path)


def test_open_source_path_linux(monkeypatch, search_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(search_tab_module.sys, "platform", "linux")

    def fake_popen(args):
        called["args"] = args
        class _Proc:
            def __init__(self):
                self.args = args
        return _Proc()

    monkeypatch.setattr(search_tab_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(search_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    search_tab.open_source_path(str(file_path))
    assert called["args"] == ["xdg-open", str(file_path)]


def test_handle_results_cell_clicked_invokes_manager(search_tab_with_manager):
    tab, manager = search_tab_with_manager
    tab.results_table.setRowCount(1)
    item = QTableWidgetItem("C:/docs/file.txt")
    item.setData(Qt.UserRole, "C:/docs/file.txt")
    tab.results_table.setItem(0, 1, item)

    tab.handle_results_cell_clicked(0, 1)
    assert manager.calls[0] == ("open", "default", True, "C:/docs/file.txt")


def test_context_menu_actions(monkeypatch, search_tab_with_manager):
    tab, manager = search_tab_with_manager
    tab.results_table.setRowCount(1)
    item = QTableWidgetItem("/tmp/doc.txt")
    item.setData(Qt.UserRole, "/tmp/doc.txt")
    tab.results_table.setItem(0, 1, item)

    def fake_index_at(_pos):
        return tab.results_table.model().index(0, 1)

    class _MenuStub:
        def __init__(self, _parent):
            self.actions = []

        def addAction(self, label):
            self.actions.append(label)
            return label

        def exec(self, _pos):
            return self.actions[self.selection]

    monkeypatch.setattr(tab.results_table, "indexAt", fake_index_at)
    monkeypatch.setattr(tab.results_table.viewport(), "mapToGlobal", lambda p: p)

    original_menu = search_tab_module.QMenu

    try:
        scenarios = [
            (0, ("open", "default", True, "/tmp/doc.txt")),
            (1, ("open", "open_with", True, "/tmp/doc.txt")),
            (2, ("open", "show_in_folder", False, "/tmp/doc.txt")),
            (3, ("open", "copy_path", False, "/tmp/doc.txt")),
            (4, ("queue", "/tmp/doc.txt", True)),
            (5, ("reindex", "/tmp/doc.txt")),
            (6, ("remove", "/tmp/doc.txt")),
        ]

        for selection, expected in scenarios:
            def factory(parent):
                menu = _MenuStub(parent)
                menu.selection = selection
                return menu

            monkeypatch.setattr(search_tab_module, "QMenu", factory)
            manager.calls.clear()
            tab.show_results_context_menu(QPoint(0, 0))
            assert manager.calls[0] == expected

        manager._queued = True

        def factory(parent):
            menu = _MenuStub(parent)
            menu.selection = 4
            return menu

        monkeypatch.setattr(search_tab_module, "QMenu", factory)
        manager.calls.clear()
        tab.show_results_context_menu(QPoint(0, 0))
        assert manager.calls[0] == ("queue", "/tmp/doc.txt", False)
    finally:
        monkeypatch.setattr(search_tab_module, "QMenu", original_menu)
