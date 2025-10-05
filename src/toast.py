from __future__ import annotations
from typing import Optional, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .websocket.message import Message

import asyncio
from .websocket.message import ShowToast, ToastType
from .models.toast import Toast

_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


def initialize_sync_toasting(loop: asyncio.AbstractEventLoop):
    global _main_event_loop
    _main_event_loop = loop


async def _toast_message_async(
    id: Optional[str],
    toast_type: Optional[Literal["success", "info", "warn", "error", "loading"]],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    from .websocket.server import get_message_queue

    toast_type_enum = None
    if toast_type:
        toast_type_enum = ToastType(toast_type)

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
    id: Optional[str],
    toast_type: Optional[Literal["success", "info", "warn", "error", "loading"]],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    if _main_event_loop and _main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            _toast_message_async(id, toast_type, message, description, cancel),
            _main_event_loop,
        )
    else:
        print(
            f"[TOAST-{toast_type.upper() if toast_type else 'GENERAL'}] {message}: {description}"
        )


def toast(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, None, message, description, cancel)


def toast_success(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, "success", message, description, cancel)


def toast_info(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, "info", message, description, cancel)


def toast_warn(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, "warn", message, description, cancel)


def toast_error(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, "error", message, description, cancel)


def toast_loading(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional[Message],
) -> None:
    _toast_message(id, "loading", message, description, cancel)
