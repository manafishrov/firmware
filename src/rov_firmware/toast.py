"""Toast notification utilities for the ROV firmware."""

import asyncio

from .models.toast import Toast, ToastAction, ToastArgs, ToastContent, ToastVariant
from .websocket.message import ShowToast
from .websocket.queue import get_message_queue
from .websocket.state import websocket_state


def toast_action(
    message_type: str,
    payload: object | None = None,
    *,
    label_key: str | None = None,
    label_args: ToastArgs | None = None,
) -> ToastAction:
    """Create a toast action payload."""
    return ToastAction(
        message_type=message_type,
        payload=payload,
        label_key=label_key,
        label_args=label_args,
    )


def cancel_thruster_test_action(thruster_index: int) -> ToastAction:
    """Create action metadata for cancelling a thruster test."""
    return toast_action(
        "cancelThrusterTest",
        thruster_index,
        label_key="common_cancel",
    )


def cancel_regulator_auto_tuning_action() -> ToastAction:
    """Create action metadata for cancelling regulator auto tuning."""
    return toast_action(
        "cancelRegulatorAutoTuning",
        label_key="common_cancel",
    )


async def _toast_message_async(payload: Toast) -> None:
    message_model = ShowToast(payload=payload)
    await get_message_queue().put(message_model)


def _toast_message(payload: Toast) -> None:
    if websocket_state.main_event_loop and websocket_state.main_event_loop.is_running():
        _ = asyncio.run_coroutine_threadsafe(
            _toast_message_async(payload),
            websocket_state.main_event_loop,
        )


def toast_content(
    identifier: str | None,
    variant: ToastVariant | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send a toast payload over websocket."""
    _toast_message(
        Toast(
            identifier=identifier,
            variant=variant,
            content=content,
            action=action,
        )
    )


def toast(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send a toast without explicitly setting variant."""
    toast_content(identifier, None, content, action)


def toast_success(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send a success toast."""
    toast_content(identifier, ToastVariant.SUCCESS, content, action)


def toast_info(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send an info toast."""
    toast_content(identifier, ToastVariant.INFO, content, action)


def toast_warn(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send a warning toast."""
    toast_content(identifier, ToastVariant.WARN, content, action)


def toast_error(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send an error toast."""
    toast_content(identifier, ToastVariant.ERROR, content, action)


def toast_loading(
    identifier: str | None,
    content: ToastContent,
    action: ToastAction | None,
) -> None:
    """Send a loading toast."""
    toast_content(identifier, ToastVariant.LOADING, content, action)
