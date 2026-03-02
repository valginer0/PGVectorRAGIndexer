import pytest
from unittest.mock import MagicMock, call, patch

from desktop_app.ui.settings_tab import SettingsTab
from desktop_app.utils.controller_result import ControllerResult, UiAction, BackendSaveData

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
    from desktop_app.ui.settings_tab import Theme # Mocking dynamic property
    mock_tab.Theme = MagicMock()
    mock_tab.Theme.SUCCESS = "#10b981"
    
    result = ControllerResult(
        success=True,
        message="Message Body",
        severity="success",
        ui_actions=[UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO],
        data=BackendSaveData(status_text="Updated label text")
    )
    
    mock_tab._handle_controller_result(result, title="Success Title")
    
    # 1. Assert status label was updated with success coloring
    mock_tab._backend_status.setText.assert_called_with("Updated label text")
    assert "color: #10b981" in mock_tab._backend_status.setStyleSheet.call_args[0][0]
    
    # 2. Assert message box was popped with info severity
    mock_msg_box.information.assert_called_once_with(mock_tab, "Success Title", "Message Body")

@patch('desktop_app.ui.settings_tab.QMessageBox')
def test_dispatcher_warning_box_only(mock_msg_box, mock_tab):
    """Verifies validation branch behavior (Warning box, no status change)."""
    result = ControllerResult(
        success=False,
        message="Missing URL",
        severity="warning",
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
        severity="error",
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
        severity="info",
        ui_actions=[UiAction.STATUS_LABEL, UiAction.NONE],
        data=BackendSaveData()
    )
    
    with pytest.raises(ValueError, match="UiAction.NONE must be the only action"):
        mock_tab._handle_controller_result(result, title="Mix")
