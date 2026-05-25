import os
import pytest
from unittest.mock import MagicMock, call, patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from desktop_app.ui.settings_tab import SettingsTab
from desktop_app.utils.controller_result import ControllerResult, MessageSeverity, UiAction, BackendSaveData
from desktop_app.utils.controller_result import MessageSeverity


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def mock_tab():
    tab = MagicMock()
    # Mock some basic UI widgets needed by the dispatcher
    tab._backend_status = MagicMock()
    # Apply the dispatcher logic onto our mock object
    from desktop_app.ui.settings_tab import SettingsTab
    tab._handle_controller_result = SettingsTab._handle_controller_result.__get__(tab)
    return tab


@patch('desktop_app.ui.settings_tab.QMessageBox')
def test_dispatcher_success_status_and_info(mock_msg_box, mock_tab):
    """Verifies that the dispatcher executes STATUS_LABEL then MESSAGE_BOX_INFO sequentially."""
    from desktop_app.ui.styles.theme import Theme
    
    result = ControllerResult(
        success=True,
        message="Message Body",
        severity=MessageSeverity.SUCCESS,
        ui_actions=[UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO],
        data=BackendSaveData(status_text="Updated label text")
    )
    
    mock_tab._handle_controller_result(result, title="Success Title")
    
    # 1. Assert status label was updated with success coloring
    mock_tab._backend_status.setText.assert_called_with("Updated label text")
    assert f"color: {Theme.SUCCESS}" in mock_tab._backend_status.setStyleSheet.call_args[0][0]
    
    # 2. Assert message box was popped with info severity
    mock_msg_box.information.assert_called_once_with(mock_tab, "Success Title", "Message Body")

@patch('desktop_app.ui.settings_tab.QMessageBox')
def test_dispatcher_warning_box_only(mock_msg_box, mock_tab):
    """Verifies validation branch behavior (Warning box, no status change)."""
    result = ControllerResult(
        success=False,
        message="Missing URL",
        severity=MessageSeverity.WARNING,
        ui_actions=[UiAction.MESSAGE_BOX_WARNING],
        data=BackendSaveData()
    )
    
    mock_tab._handle_controller_result(result, title="Validation Error")
    
    # Status label shouldn't be touched
    mock_tab._backend_status.setText.assert_not_called()
    
    # Warning box should fire
    mock_msg_box.warning.assert_called_once_with(mock_tab, "Validation Error", "Missing URL")

@patch('desktop_app.ui.settings_tab.QMessageBox')
def test_dispatcher_multiple_actions_are_ordered_and_not_deduplicated(mock_msg_box, mock_tab):
    """Verifies the contract that actions execute sequentially without deduplication."""
    result = ControllerResult(
        success=False,
        message="Oops",
        severity=MessageSeverity.ERROR,
        ui_actions=[UiAction.MESSAGE_BOX_ERROR, UiAction.MESSAGE_BOX_WARNING],
        data=BackendSaveData()
    )
    
    mock_tab._handle_controller_result(result, title="Err")
    
    mock_msg_box.critical.assert_called_once_with(mock_tab, "Err", "Oops")
    mock_msg_box.warning.assert_called_once_with(mock_tab, "Err", "Oops")

def test_dispatcher_none_action_must_be_alone(mock_tab):
    """Verifies that mixing UiAction.NONE with other actions raises a ValueError."""
    result = ControllerResult(
        success=True,
        message="Bad mix",
        severity=MessageSeverity.INFO,
        ui_actions=[UiAction.STATUS_LABEL, UiAction.NONE],
        data=BackendSaveData()
    )
    
    with pytest.raises(ValueError, match="UiAction.NONE must be the only action"):
        mock_tab._handle_controller_result(result, title="Mix")


def test_search_panel_document_level_checkbox_wires_config(qapp):
    """The experimental document-level search checkbox reads and writes app config."""
    setter = MagicMock()

    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"), \
         patch("desktop_app.utils.app_config.set_document_level_search_enabled", setter):
        tab = SettingsTab(docker_manager=MagicMock())

        checkbox = tab._document_level_search_checkbox
        assert checkbox.isChecked() is False

        checkbox.setChecked(True)

    setter.assert_called_once_with(True)


def test_search_panel_local_lancedb_checkbox_wires_config(qapp):
    """The local LanceDB checkbox reads and writes app config."""
    setter = MagicMock()

    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"), \
         patch("desktop_app.utils.app_config.set_local_lancedb_search_enabled", setter):
        tab = SettingsTab(docker_manager=MagicMock())

        checkbox = tab._local_lancedb_search_checkbox
        assert checkbox.isChecked() is False
        assert tab._local_lancedb_index_btn.text() == "Rebuild Local Text Index"
        assert "overwrites" in tab._local_lancedb_index_btn.toolTip()

        checkbox.setChecked(True)

    setter.assert_called_once_with(True)


def test_build_local_lancedb_index_starts_worker(qapp, tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()

    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"), \
         patch("desktop_app.ui.settings_tab.QFileDialog.getExistingDirectory", return_value=str(folder)), \
         patch("desktop_app.ui.settings_tab.LocalLanceDBIngestWorker") as MockWorker:
        worker = MockWorker.return_value
        tab = SettingsTab(docker_manager=MagicMock())

        tab._build_local_lancedb_index()

        MockWorker.assert_called_once_with([Path(folder)], "/tmp/local-lancedb")
        worker.progress.connect.assert_called_once_with(tab._local_lancedb_ingest_progress)
        worker.finished.connect.assert_called_once_with(tab._local_lancedb_ingest_finished)
        worker.start.assert_called_once()
        assert tab._local_lancedb_index_btn.isEnabled() is False


def test_build_local_lancedb_index_rejects_busy_index(qapp):
    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"), \
         patch("desktop_app.ui.settings_tab.is_lancedb_index_busy", return_value=True), \
         patch("desktop_app.ui.settings_tab.QFileDialog.getExistingDirectory") as mock_dialog, \
         patch("desktop_app.ui.settings_tab.QMessageBox.warning") as mock_warn, \
         patch("desktop_app.ui.settings_tab.LocalLanceDBIngestWorker") as MockWorker:
        tab = SettingsTab(docker_manager=MagicMock())

        tab._build_local_lancedb_index()

        mock_warn.assert_called_once()
        mock_dialog.assert_not_called()
        MockWorker.assert_not_called()
        assert tab._local_lancedb_index_btn.isEnabled() is True


def test_local_lancedb_ingest_finished_updates_status(qapp):
    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"):
        tab = SettingsTab(docker_manager=MagicMock())

        tab._local_lancedb_index_btn.setEnabled(False)
        tab._local_lancedb_ingest_finished(
            True,
            {"indexed_documents": 2, "chunk_count": 5, "skipped_files": [{}, {}]},
        )

    assert tab._local_lancedb_index_btn.isEnabled() is True
    assert "Indexed 2 documents, 5 chunks; skipped 2." == tab._local_lancedb_status.text()


def test_local_lancedb_ingest_progress_updates_status(qapp):
    with patch("desktop_app.ui.settings_tab.qta.icon", return_value=QIcon()), \
         patch("desktop_app.utils.app_config.get_document_level_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_search_enabled", return_value=False), \
         patch("desktop_app.utils.app_config.get_local_lancedb_db_path", return_value="/tmp/local-lancedb"):
        tab = SettingsTab(docker_manager=MagicMock())

        tab._local_lancedb_ingest_progress("Loading local embedding model...")

    assert tab._local_lancedb_status.text() == "Loading local embedding model..."
    assert "color:" in tab._local_lancedb_status.styleSheet()
