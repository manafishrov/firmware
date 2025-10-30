"""Toast notification utilities for the ROV firmware."""

from __future__ import annotations

import asyncio

from .models.toast import Toast, ToastCancel, ToastType
from .websocket.message import CancelRegulatorAutoTuning, CancelThrusterTest, ShowToast


_main_event_loop: asyncio.AbstractEventLoop | None = None


def initialize_sync_toasting(loop: asyncio.AbstractEventLoop) -> None:
    """Initialize synchronous toasting.

    Args:
        loop: The asyncio event loop.
    """
    global _main_event_loop
    _main_event_loop = loop


async def _toast_message_async(
    toast_id: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    from .websocket.server import get_message_queue

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
    if _main_event_loop and _main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            _toast_message_async(toast_id, toast_type, message, description, cancel),
            _main_event_loop,
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
