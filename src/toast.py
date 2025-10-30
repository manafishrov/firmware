from __future__ import annotations

import asyncio

from .models.toast import Toast, ToastCancel, ToastType
from .websocket.message import CancelRegulatorAutoTuning, CancelThrusterTest, ShowToast


_main_event_loop: asyncio.AbstractEventLoop | None = None


def initialize_sync_toasting(loop: asyncio.AbstractEventLoop) -> None:
    global _main_event_loop
    _main_event_loop = loop


async def _toast_message_async(
    id: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    from .websocket.server import get_message_queue

    toast_type_enum = toast_type

    payload = Toast(
        id=id,
        toast_type=toast_type_enum,
        message=message,
        description=description,
        cancel=cancel,
    )
    message_model = ShowToast(payload=payload)
    await get_message_queue().put(message_model)


def _toast_message(
    id: str | None,
    toast_type: ToastType | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    if _main_event_loop and _main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            _toast_message_async(id, toast_type, message, description, cancel),
            _main_event_loop,
        )
    else:
        pass


def toast(
    id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    _toast_message(id, None, message, description, cancel)


def toast_success(
    id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    _toast_message(id, ToastType.SUCCESS, message, description, cancel)


def toast_info(
    id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    _toast_message(id, ToastType.INFO, message, description, cancel)


def toast_warn(
    id: str | None,
    message: str,
    description: str | None,
    cancel: ToastCancel | None,
) -> None:
    _toast_message(id, ToastType.WARN, message, description, cancel)


def toast_error(
    id: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    _toast_message(id, ToastType.ERROR, message, description, cancel)


def toast_loading(
    id: str | None,
    message: str,
    description: str | None,
    cancel: CancelRegulatorAutoTuning | CancelThrusterTest | None,
) -> None:
    _toast_message(id, ToastType.LOADING, message, description, cancel)
