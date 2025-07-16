from typing import Optional, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_types import Cancel


async def _toast_message(
    id: Optional[str],
    toast_type: Optional[Literal["success", "info", "warn", "error", "loading"]],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    from websocket_server import get_message_queue

    await get_message_queue().put(
        {
            "type": "showToast",
            "payload": {
                "id": id,
                "toastType": toast_type,
                "message": message,
                "description": description,
                "cancel": cancel,
            },
        }
    )


async def toast(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, None, message, description, cancel)


async def toast_success(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, "success", message, description, cancel)


async def toast_info(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, "info", message, description, cancel)


async def toast_warn(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, "warn", message, description, cancel)


async def toast_error(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, "error", message, description, cancel)


async def toast_loading(
    id: Optional[str],
    message: str,
    description: Optional[str],
    cancel: Optional["Cancel"],
) -> None:
    await _toast_message(id, "error", message, description, cancel)
