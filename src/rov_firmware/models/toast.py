"""Toast data models for the ROV firmware."""

from enum import StrEnum

from .base import CamelCaseModel


class ToastVariant(StrEnum):
    """Supported visual variants for toast notifications."""

    SUCCESS = "success"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    LOADING = "loading"


ToastArgs = dict[str, str | int | float | bool]


class ToastAction(CamelCaseModel):
    """Action metadata rendered as a toast action button."""

    label_key: str | None = None
    label_args: ToastArgs | None = None
    message_type: str
    payload: object | None = None


class ToastContent(CamelCaseModel):
    """Localized toast text payload and optional interpolation args."""

    message_key: str
    message_args: ToastArgs | None = None
    description_key: str | None = None
    description_args: ToastArgs | None = None


class Toast(CamelCaseModel):
    """Model for toast notifications."""

    identifier: str | None
    variant: ToastVariant | None
    content: ToastContent
    action: ToastAction | None
