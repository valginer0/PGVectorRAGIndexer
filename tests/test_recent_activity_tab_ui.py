import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QHeaderView

from desktop_app.ui.recent_activity_tab import RecentActivityTab
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
