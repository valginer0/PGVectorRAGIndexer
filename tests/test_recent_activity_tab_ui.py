from datetime import datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QHeaderView

from desktop_app.ui.recent_activity_tab import RecentActivityTab, RecentEntry
from desktop_app.ui.source_open_manager import SourceOpenManager


class _DummyApiClient:
    def upload_document(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def recent_tab(qt_app):
    manager = SourceOpenManager(_DummyApiClient())
    tab = RecentActivityTab(manager)
    return tab


def test_recent_tab_path_column_resizable(recent_tab):
    header = recent_tab.table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Interactive


def test_recent_tab_path_tooltip_and_elide_mode(recent_tab):
    entry = RecentEntry(path="/tmp/example.txt", opened_at=datetime.utcnow())
    recent_tab._handle_entry_added(entry)

    item = recent_tab.table.item(0, 0)

    assert recent_tab.table.textElideMode() == Qt.ElideNone
    assert item is not None
    assert item.toolTip() == "/tmp/example.txt"
