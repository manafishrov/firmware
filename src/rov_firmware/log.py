"""Logging utilities for the ROV firmware."""

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
import concurrent.futures
from datetime import UTC, datetime
import logging
from pathlib import Path
import threading
import time
import uuid

from .log_buffer import BoundedJournalHandler
from .models.log import LogEntry, LogLevel, LogOrigin
from .websocket.message import LogMessage
from .websocket.queue import get_message_queue
from .websocket.state import websocket_state


_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _logger.addHandler(BoundedJournalHandler(_handler))


_MAX_PENDING_LOGS = 100
_MAX_LOG_QUEUE_DEPTH = 200
_flush_scheduled = False
_pending_logs: deque[LogMessage] = deque(maxlen=_MAX_PENDING_LOGS)
_pending_lock = threading.Lock()
_dropped_logs = 0
_SESSION_ID = uuid.uuid4().hex
try:
    _BOOT_ID = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
except OSError:
    _BOOT_ID = "unavailable"


def get_local_logger() -> logging.Logger:
    """Return the bounded journal logger for failures that must not recurse."""
    return _logger


def stamp_log_message(message: str) -> str:
    """Keep Pi generation time even when the app receives a buffered log later."""
    return (
        f"[pi session={_SESSION_ID} boot={_BOOT_ID} "
        f"mono_s={time.monotonic():.3f} utc={datetime.now(UTC).isoformat()}] {message}"
    )


def _buffer_log(message: LogMessage) -> None:
    global _dropped_logs  # noqa: PLW0603 - guarded by _pending_lock
    with _pending_lock:
        if len(_pending_logs) == _MAX_PENDING_LOGS:
            _dropped_logs += 1
        _pending_logs.append(message)


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
    """Flush only available log capacity; never limit control/config messages."""
    global _dropped_logs  # noqa: PLW0603 - guarded by _pending_lock
    queue = get_message_queue()
    while queue.qsize() < _MAX_LOG_QUEUE_DEPTH:
        with _pending_lock:
            if _dropped_logs:
                message = LogMessage(
                    payload=LogEntry(
                        origin=LogOrigin.FIRMWARE,
                        level=LogLevel.WARN,
                        message=stamp_log_message(
                            f"Debug log buffer discarded {_dropped_logs} older records; "
                            f"replaying the latest {len(_pending_logs)}. The local journal may contain earlier records."
                        ),
                    )
                )
                _dropped_logs = 0
            elif _pending_logs:
                message = _pending_logs.popleft()
            else:
                return
        queue.put_nowait(message)


async def _flush_when_connected() -> None:
    global _flush_scheduled  # noqa: PLW0603 - guarded by _pending_lock
    completed = False
    try:
        while websocket_state.is_client_connected:
            await flush_pending_logs()
            with _pending_lock:
                if not _pending_logs:
                    break
            await asyncio.sleep(0.25)
        completed = True
    finally:
        with _pending_lock:
            _flush_scheduled = False
        # A worker thread may append between the empty check and flag reset.
        if completed:
            _schedule_flush()


def _schedule_flush() -> None:
    global _flush_scheduled  # noqa: PLW0603 - guarded by _pending_lock
    if not websocket_state.is_client_connected:
        return
    with _pending_lock:
        if _flush_scheduled or not _pending_logs:
            return
        _flush_scheduled = True
    if not submit_to_main_loop(_flush_when_connected, "flush_debug_logs"):
        with _pending_lock:
            _flush_scheduled = False


def _log_message(
    level: LogLevel, message: str, origin: LogOrigin = LogOrigin.FIRMWARE
) -> None:
    message = stamp_log_message(message)
    # Always retain a local copy, including while an app is connected.
    _logger.log(_map_log_level(level), "[%s] %s", origin.value, message)
    _buffer_log(
        LogMessage(payload=LogEntry(origin=origin, level=level, message=message))
    )
    _schedule_flush()


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
