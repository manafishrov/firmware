from __future__ import annotations
import asyncio
from typing import Optional

_is_client_connected: bool = False
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


def initialize_sync_logging(loop: asyncio.AbstractEventLoop):
    global _main_event_loop
    _main_event_loop = loop


def set_log_is_client_connected_status(is_connected: bool) -> None:
    global _is_client_connected
    _is_client_connected = is_connected


async def _log_message_async(level: str, message: str) -> None:
    if _is_client_connected:
        from .websocket.server import get_message_queue

        await get_message_queue().put(
            {
                "type": "logMessage",
                "payload": {"origin": "firmware", "level": level, "message": message},
            }
        )
    else:
        print(f"{level.upper()}: {message}")


def _log_message(level: str, message: str) -> None:
    if _main_event_loop and _main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            _log_message_async(level, message), _main_event_loop
        )
    else:
        print(f"{level.upper()}: {message}")


def log_info(message: str) -> None:
    _log_message("info", message)


def log_warn(message: str) -> None:
    _log_message("warn", message)


def log_error(message: str) -> None:
    _log_message("error", message)
