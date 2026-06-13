"""Logging utilities for the ROV firmware."""

import asyncio
from collections.abc import Callable, Coroutine
import concurrent.futures
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


def _log_future_failure(future: concurrent.futures.Future[None], label: str) -> None:
    try:
        _ = future.result()
    except concurrent.futures.CancelledError:
        pass
    except Exception:
        # Local logger, not log_error, to avoid recursion on logging failures.
        _logger.exception("Background coroutine failed: %s", label)


def submit_to_main_loop(
    coro_factory: Callable[[], Coroutine[object, object, None]], label: str
) -> bool:
    """Schedule a coroutine on the main loop, logging any failure.

    Args:
        coro_factory: Builds the coroutine; called only once the loop is running.
        label: Label used in failure logs.

    Returns:
        True if the coroutine was scheduled, False otherwise.
    """
    loop = websocket_state.main_event_loop
    if loop is None or not loop.is_running():
        return False

    try:
        future = asyncio.run_coroutine_threadsafe(coro_factory(), loop)
    except Exception:
        _logger.exception("Failed to submit %s", label)
        return False

    future.add_done_callback(lambda f: _log_future_failure(f, label))
    return True


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
    scheduled = submit_to_main_loop(
        lambda: _log_message_async(level, message, origin),
        f"log_message[{level}]",
    )
    if not scheduled:
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
