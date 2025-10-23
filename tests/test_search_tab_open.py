import os
import sys
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt

import desktop_app.ui.search_tab as search_tab_module
from desktop_app.ui.search_tab import SearchTab


class _DummyApiClient:
    def search(self, *args, **kwargs):
        return []

    def get_metadata_values(self, key):
        return []

    def is_api_available(self):
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


def test_handle_results_cell_clicked_invokes_open(monkeypatch, search_tab):
    search_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("C:/docs/file.txt")
    item.setData(Qt.UserRole, "C:/docs/file.txt")
    search_tab.results_table.setItem(0, 1, item)

    called = []
    monkeypatch.setattr(search_tab, "open_source_path", lambda path: called.append(path))

    search_tab.handle_results_cell_clicked(0, 1)
    assert called == ["C:/docs/file.txt"]
