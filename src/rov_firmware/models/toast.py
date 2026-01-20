"""Toast data models for the ROV firmware."""

from enum import StrEnum

from ..websocket.cancel_messages import CancelRegulatorAutoTuning, CancelThrusterTest
from .base import CamelCaseModel


class ToastType(StrEnum):
    """Enum for toast types."""

    SUCCESS = "success"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    LOADING = "loading"


ToastCancel = CancelRegulatorAutoTuning | CancelThrusterTest


class Toast(CamelCaseModel):
    """Model for toast notifications."""

    toast_id: str | None
    toast_type: ToastType | None
    message: str
    description: str | None
    cancel: ToastCancel | None
