import os
import sys
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt

import desktop_app.ui.manage_tab as manage_tab_module
from desktop_app.ui.manage_tab import ManageTab


class _DummyApiClient:
    def get_metadata_values(self, key):
        return []


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def manage_tab(qt_app):
    return ManageTab(_DummyApiClient())


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


def test_handle_results_cell_clicked_invokes_open(monkeypatch, manage_tab):
    manage_tab.results_table.setRowCount(1)
    item = QTableWidgetItem("C:/docs/file.txt")
    item.setData(Qt.UserRole, "C:/docs/file.txt")
    manage_tab.results_table.setItem(0, 2, item)

    called = []
    monkeypatch.setattr(manage_tab, "open_source_path", lambda path: called.append(path))

    manage_tab.handle_results_cell_clicked(0, 2)
    assert called == ["C:/docs/file.txt"]
