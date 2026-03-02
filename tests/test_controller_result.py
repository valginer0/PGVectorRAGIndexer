from desktop_app.utils.controller_result import (
    ControllerResult, 
    UiAction, 
    EmptyData,
    BackendSaveData
)

def test_controller_result_initialization():
    result: ControllerResult[EmptyData] = ControllerResult(
        success=True,
        message="Success",
        severity="success",
        ui_actions=[UiAction.NONE],
        data=EmptyData()
    )
    assert result.success is True
    assert result.message == "Success"
    assert result.severity == "success"
    assert result.ui_actions == [UiAction.NONE]
    assert result.data == {}

def test_controller_result_with_backend_save_data():
    result: ControllerResult[BackendSaveData] = ControllerResult(
        success=True,
        message="Saved",
        severity="info",
        ui_actions=[UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO],
        data=BackendSaveData(status_text="Settings saved.")
    )
    assert result.success is True
    assert result.ui_actions == [UiAction.STATUS_LABEL, UiAction.MESSAGE_BOX_INFO]
    assert result.data["status_text"] == "Settings saved."
