"""Logging utilities for the ROV firmware."""

import asyncio
import logging

from .models.log import LogEntry, LogLevel, LogOrigin
from .websocket.message import LogMessage
from .websocket.queue import get_message_queue
from .websocket.state import websocket_state


_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _logger.addHandler(_handler)


_MAX_PENDING_LOGS = 100
_pending_logs: list[LogMessage] = []


async def flush_pending_logs() -> None:
    """Flush pre-connection logs to the websocket message queue."""
    queue = get_message_queue()
    for msg in _pending_logs:
        await queue.put(msg)
    _pending_logs.clear()


async def _log_message_async(
    level: LogLevel, message: str, origin: LogOrigin = LogOrigin.FIRMWARE
) -> None:
    payload = LogEntry(origin=origin, level=LogLevel(level), message=message)
    message_model = LogMessage(payload=payload)

    if websocket_state.is_client_connected:
        await get_message_queue().put(message_model)
    else:
        if len(_pending_logs) < _MAX_PENDING_LOGS:
            _pending_logs.append(message_model)
        _logger.log(_map_log_level(level), message)


def _log_message(
    level: LogLevel, message: str, origin: LogOrigin = LogOrigin.FIRMWARE
) -> None:
    if websocket_state.main_event_loop and websocket_state.main_event_loop.is_running():
        _ = asyncio.run_coroutine_threadsafe(
            _log_message_async(level, message, origin),
            websocket_state.main_event_loop,
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


def log_info(*args: object, origin: LogOrigin = LogOrigin.FIRMWARE) -> None:
    """Log an info message.

    Accepts any number of arguments of any type, like ``print()``.

    Args:
        *args: Values to log, joined by spaces.
        origin: The origin of the log message.
    """
    _log_message(LogLevel.INFO, " ".join(str(a) for a in args), origin)


def log_warn(*args: object, origin: LogOrigin = LogOrigin.FIRMWARE) -> None:
    """Log a warning message.

    Accepts any number of arguments of any type, like ``print()``.

    Args:
        *args: Values to log, joined by spaces.
        origin: The origin of the log message.
    """
    _log_message(LogLevel.WARN, " ".join(str(a) for a in args), origin)


def log_error(*args: object, origin: LogOrigin = LogOrigin.FIRMWARE) -> None:
    """Log an error message.

    Accepts any number of arguments of any type, like ``print()``.

    Args:
        *args: Values to log, joined by spaces.
        origin: The origin of the log message.
    """
    _log_message(LogLevel.ERROR, " ".join(str(a) for a in args), origin)
