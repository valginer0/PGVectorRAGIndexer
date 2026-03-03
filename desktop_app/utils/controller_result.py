from dataclasses import dataclass
from enum import Enum, auto
from typing import Generic, Literal, TypedDict, TypeVar, Optional
from desktop_app.utils.license_dto import LicenseDisplayDTO

T = TypeVar('T')

class UiAction(Enum):
    STATUS_LABEL = auto()
    MESSAGE_BOX_INFO = auto()
    MESSAGE_BOX_WARNING = auto()
    MESSAGE_BOX_ERROR = auto()
    NONE = auto()

class MessageSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"

class LicenseLoadData(TypedDict):
    info: Optional[LicenseDisplayDTO]
    server_error: bool

class BackendSaveData(TypedDict, total=False):
    status_text: str

class EmptyData(TypedDict):
    pass

@dataclass
class ControllerResult(Generic[T]):
    success: bool
    message: str
    severity: MessageSeverity
    ui_actions: list[UiAction]
    data: T
