"""Toast notification utilities for the ROV firmware."""

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
    identifier: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    toast_type_enum = toast_type

    payload = Toast(
        identifier=identifier,
        toast_type=toast_type_enum,
        message=message,
        description=description,
        cancel=cancel,
    )
    message_model = ShowToast(payload=payload)
    await get_message_queue().put(message_model)


def _toast_message(
    identifier: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    if websocket_state.main_event_loop and websocket_state.main_event_loop.is_running():
        _ = asyncio.run_coroutine_threadsafe(
            _toast_message_async(identifier, toast_type, message, description, cancel),
            websocket_state.main_event_loop,
        )


def toast(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, None, message, description, cancel)


def toast_success(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a success toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, ToastType.SUCCESS, message, description, cancel)


def toast_info(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send an info toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, ToastType.INFO, message, description, cancel)


def toast_warn(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    """Send a warning toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, ToastType.WARN, message, description, cancel)


def toast_error(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    """Send an error toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, ToastType.ERROR, message, description, cancel)


def toast_loading(
    identifier: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    """Send a loading toast notification.

    Args:
        identifier: The toast identifier.
        message: The message.
        description: The description.
        cancel: The cancel action.
    """
    _toast_message(identifier, ToastType.LOADING, message, description, cancel)
