"""Toast notification utilities for the ROV firmware."""

from __future__ import annotations

import asyncio

from .models.toast import Toast, ToastCancel, ToastType
from .websocket.cancel_messages import (
    CancelRegulatorAutoTuning,
    CancelThrusterTest,
)
from .websocket.message import (
    ShowToast,
)
from .websocket.queue import get_message_queue
from .websocket.state import websocket_state


async def _toast_message_async(
    toast_id: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    toast_type_enum = toast_type

    payload = Toast(
        toast_id=toast_id,
        toast_type=toast_type_enum,
        message=message,
        description=description,
        cancel=cancel,
    )
    message_model = ShowToast(payload=payload)
    await get_message_queue().put(message_model)


def _toast_message(
    toast_id: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    if websocket_state.main_event_loop and websocket_state.main_event_loop.is_running():
        _ = asyncio.run_coroutine_threadsafe(
            _toast_message_async(toast_id, toast_type, message, description, cancel),
            websocket_state.main_event_loop,
        )


def toast(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, None, message, description, cancel)


def toast_success(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a success toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, ToastType.SUCCESS, message, description, cancel)


def toast_info(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send an info toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, ToastType.INFO, message, description, cancel)


def toast_warn(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a warning toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, ToastType.WARN, message, description, cancel)


def toast_error(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    """Send an error toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, ToastType.ERROR, message, description, cancel)


def toast_loading(
    toast_id: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    """Send a loading toast notification.

    Args:
        toast_id: The toast ID.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(toast_id, ToastType.LOADING, message, description, cancel)
