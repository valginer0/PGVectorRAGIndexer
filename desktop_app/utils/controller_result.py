from dataclasses import dataclass
from enum import Enum, auto
from typing import Generic, Literal, TypedDict, TypeVar

T = TypeVar('T')

class UiAction(Enum):
    STATUS_LABEL = auto()
    MESSAGE_BOX_INFO = auto()
    MESSAGE_BOX_WARNING = auto()
    MESSAGE_BOX_ERROR = auto()
    NONE = auto()

class LicenseDisplayDTO(TypedDict):
    edition: str
    expiration: str
    owner: str

class LicenseLoadData(TypedDict):
    info: LicenseDisplayDTO
    server_error: bool

class BackendSaveData(TypedDict, total=False):
    status_text: str

class EmptyData(TypedDict):
    pass

@dataclass
class ControllerResult(Generic[T]):
    success: bool
    message: str
    severity: Literal['info', 'warning', 'error', 'success']
    ui_actions: list[UiAction]
    data: T
