import os
import sys
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt, QPoint

import desktop_app.ui.search_tab as search_tab_module
from desktop_app.ui.search_tab import SearchTab


class _DummyApiClient:
    def search(self, *args, **kwargs):
        return []

    def get_metadata_values(self, key):
        return []

    def is_api_available(self):
        return True


class _StubManager:
    def __init__(self):
        self.calls = []

    def open_path(self, path: str, mode: str = "default", prompt_reindex: bool = True):
        self.calls.append((mode, prompt_reindex, path))

    def trigger_reindex_path(self, path: str):
        self.calls.append(("reindex", True, path))
        return True


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
    assert manager.calls[0] == ("default", True, "C:/docs/file.txt")


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
        for selection, expected in [
            (0, ("default", True, "/tmp/doc.txt")),
            (1, ("open_with", True, "/tmp/doc.txt")),
            (2, ("show_in_folder", False, "/tmp/doc.txt")),
            (3, ("copy_path", False, "/tmp/doc.txt")),
            (4, ("reindex", True, "/tmp/doc.txt")),
        ]:
            def factory(parent):
                menu = _MenuStub(parent)
                menu.selection = selection
                return menu

            monkeypatch.setattr(search_tab_module, "QMenu", factory)
            manager.calls.clear()
            tab.show_results_context_menu(QPoint(0, 0))
            assert manager.calls[0] == expected
    finally:
        monkeypatch.setattr(search_tab_module, "QMenu", original_menu)
