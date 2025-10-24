import os
import sys
import subprocess
from pathlib import Path

import pytest
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt, QPoint

import desktop_app.ui.manage_tab as manage_tab_module
from desktop_app.ui.manage_tab import ManageTab


class _DummyApiClient:
    def get_metadata_values(self, key):
        return []


class _StubManager:
    def __init__(self, queued: bool = False):
        self.calls = []
        self._queued = queued

    def open_path(self, path: str, mode: str = "default", auto_queue: bool = True) -> None:
        self.calls.append(("open", mode, auto_queue, path))

    def trigger_reindex_path(self, path: str) -> bool:
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
def manage_tab(qt_app):
    return ManageTab(_DummyApiClient())


@pytest.fixture
def managed_with_tracker(qt_app):
    manager = _StubManager()
    tab = ManageTab(_DummyApiClient(), source_manager=manager)
    return tab, manager


def test_open_source_path_no_path_shows_warning(monkeypatch, manage_tab):
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(manage_tab_module.QMessageBox, "warning", fake_warning)
    manage_tab.open_source_path("")
    assert captured


def test_open_source_path_missing_file(monkeypatch, manage_tab, tmp_path):
    missing_path = tmp_path / "missing.txt"
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(manage_tab_module.QMessageBox, "warning", fake_warning)
    manage_tab.open_source_path(str(missing_path))
    assert captured


def test_open_source_path_windows(monkeypatch, manage_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(manage_tab_module.sys, "platform", "win32")

    def fake_startfile(path):
        called["path"] = path

    monkeypatch.setattr(manage_tab_module.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(manage_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    manage_tab.open_source_path(str(file_path))
    assert called["path"] == str(file_path)


def test_open_source_path_linux(monkeypatch, manage_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(manage_tab_module.sys, "platform", "linux")

    def fake_popen(args):
        called["args"] = args
        class _Proc:
            def __init__(self):
                self.args = args
        return _Proc()

    monkeypatch.setattr(manage_tab_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(manage_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    manage_tab.open_source_path(str(file_path))
    assert called["args"] == ["xdg-open", str(file_path)]


def test_handle_results_cell_clicked_invokes_manager(managed_with_tracker):
    tab, manager = managed_with_tracker
    tab.results_table.setRowCount(1)
    item = QTableWidgetItem("C:/docs/file.txt")
    item.setData(Qt.UserRole, "C:/docs/file.txt")
    tab.results_table.setItem(0, 2, item)

    tab.handle_results_cell_clicked(0, 2)
    assert manager.calls[0] == ("open", "default", True, "C:/docs/file.txt")


def test_context_menu_actions(monkeypatch, managed_with_tracker, qt_app):
    tab, manager = managed_with_tracker
    tab.results_table.setRowCount(1)
    item = QTableWidgetItem("/tmp/doc.txt")
    item.setData(Qt.UserRole, "/tmp/doc.txt")
    tab.results_table.setItem(0, 2, item)

    def fake_index_at(pos):
        return tab.results_table.model().index(0, 2)

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

    original_menu = manage_tab_module.QMenu

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

            monkeypatch.setattr(manage_tab_module, "QMenu", factory)
            manager.calls.clear()
            tab.show_results_context_menu(QPoint(0, 0))
            assert manager.calls[0] == expected

        # Verify queued label toggles to unqueue
        manager._queued = True

        def factory(parent):
            menu = _MenuStub(parent)
            menu.selection = 4
            return menu

        monkeypatch.setattr(manage_tab_module, "QMenu", factory)
        manager.calls.clear()
        tab.show_results_context_menu(QPoint(0, 0))
        assert manager.calls[0] == ("queue", "/tmp/doc.txt", False)
    finally:
        monkeypatch.setattr(manage_tab_module, "QMenu", original_menu)


def test_get_filters_requires_selection(monkeypatch, manage_tab):
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(manage_tab_module.QMessageBox, "warning", fake_warning)

    manage_tab.type_combo.setCurrentText("")
    manage_tab.path_filter.setText("")

    result = manage_tab.get_filters()

    assert result is None
    assert captured


def test_get_filters_converts_path_wildcards(manage_tab):
    manage_tab.type_combo.setCurrentText("")
    manage_tab.path_filter.setText(r"C:\\Projects\\*report?.txt")

    filters = manage_tab.get_filters()

    assert filters == {"source_uri_like": "C:/Projects/%report_.txt"}
