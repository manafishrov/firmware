from enum import Enum
from typing import Optional, Union
from .base import CamelCaseModel
from ..websocket.message import CancelRegulatorAutoTuning, CancelThrusterTest


class ToastType(str, Enum):
    SUCCESS = "success"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    LOADING = "loading"


ToastCancel = Union[CancelRegulatorAutoTuning, CancelThrusterTest]


class Toast(CamelCaseModel):
    id: Optional[str]
    toast_type: Optional[ToastType]
    message: str
    description: Optional[str]
    cancel: Optional[ToastCancel]
