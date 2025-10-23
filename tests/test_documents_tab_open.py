import os
import sys
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt

import desktop_app.ui.documents_tab as documents_tab_module
from desktop_app.ui.documents_tab import DocumentsTab


class _DummyApiClient:
    def is_api_available(self):
        return True

    def list_documents(self):
        return []


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def documents_tab(qt_app):
    tab = DocumentsTab(_DummyApiClient())
    tab.documents_table.setRowCount(0)
    return tab


def test_open_source_path_no_path_shows_warning(monkeypatch, documents_tab):
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(documents_tab_module.QMessageBox, "warning", fake_warning)
    documents_tab.open_source_path("")
    assert captured


def test_open_source_path_missing_file(monkeypatch, documents_tab, tmp_path):
    missing_path = tmp_path / "missing.txt"
    captured = []

    def fake_warning(parent, title, text):
        captured.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(documents_tab_module.QMessageBox, "warning", fake_warning)
    documents_tab.open_source_path(str(missing_path))
    assert captured


def test_open_source_path_windows(monkeypatch, documents_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(documents_tab_module.sys, "platform", "win32")

    def fake_startfile(path):
        called["path"] = path

    monkeypatch.setattr(documents_tab_module.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(documents_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    documents_tab.open_source_path(str(file_path))
    assert called["path"] == str(file_path)


def test_open_source_path_linux(monkeypatch, documents_tab, tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("content")
    called = {}

    monkeypatch.setattr(documents_tab_module.sys, "platform", "linux")

    def fake_popen(args):
        called["args"] = args
        class _Proc:
            def __init__(self):
                self.args = args
        return _Proc()

    monkeypatch.setattr(documents_tab_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(documents_tab_module.QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    documents_tab.open_source_path(str(file_path))
    assert called["args"] == ["xdg-open", str(file_path)]


def test_handle_documents_cell_clicked_invokes_open(monkeypatch, documents_tab):
    documents_tab.documents_table.setRowCount(1)
    item = QTableWidgetItem("C:/docs/file.txt")
    item.setData(Qt.UserRole, "C:/docs/file.txt")
    documents_tab.documents_table.setItem(0, 0, item)

    called = []

    monkeypatch.setattr(documents_tab, "open_source_path", lambda path: called.append(path))
    documents_tab.handle_documents_cell_clicked(0, 0)
    assert called == ["C:/docs/file.txt"]
