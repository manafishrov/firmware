from enum import Enum
from typing import Union

from ..websocket.message import CancelRegulatorAutoTuning, CancelThrusterTest
from .base import CamelCaseModel


class ToastType(str, Enum):
    SUCCESS = "success"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    LOADING = "loading"


ToastCancel = Union[CancelRegulatorAutoTuning, CancelThrusterTest]


class Toast(CamelCaseModel):
    id: str | None
    toast_type: ToastType | None
    message: str
    description: str | None
    cancel: ToastCancel | None
