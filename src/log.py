from __future__ import annotations

import asyncio
import logging

from .models.log import LogEntry, LogLevel, LogOrigin
from .websocket.message import LogMessage


_is_client_connected: bool = False
_main_event_loop: asyncio.AbstractEventLoop | None = None

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _logger.addHandler(_handler)


def initialize_sync_logging(loop: asyncio.AbstractEventLoop) -> None:
    global _main_event_loop
    _main_event_loop = loop


def set_log_is_client_connected_status(is_connected: bool) -> None:
    global _is_client_connected
    _is_client_connected = is_connected


async def _log_message_async(level: LogLevel, message: str) -> None:
    if _is_client_connected:
        from .websocket.server import get_message_queue

        payload = LogEntry(
            origin=LogOrigin.FIRMWARE, level=LogLevel(level), message=message
        )
        message_model = LogMessage(payload=payload)
        await get_message_queue().put(message_model)
    else:
        _logger.log(_map_log_level(level), message)


def _log_message(level: LogLevel, message: str) -> None:
    if _main_event_loop and _main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            _log_message_async(level, message), _main_event_loop
        )
    else:
        _logger.log(_map_log_level(level), message)


def _map_log_level(level: LogLevel) -> int:
    mapping = {
        LogLevel.INFO: logging.INFO,
        LogLevel.WARN: logging.WARNING,
        LogLevel.ERROR: logging.ERROR,
    }
    return mapping.get(level, logging.INFO)


def log_info(message: str) -> None:
    _log_message(LogLevel.INFO, message)


def log_warn(message: str) -> None:
    _log_message(LogLevel.WARN, message)


def log_error(message: str) -> None:
    _log_message(LogLevel.ERROR, message)
