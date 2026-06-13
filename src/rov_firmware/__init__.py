"""ROV Firmware Package Initialization.

This module exposes the main application entry point and orchestrates
the startup sequence for the ROV firmware.
"""

import asyncio
import sys
import threading
import traceback
import types

from .log import log_error, log_info
from .main import main


def _excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: types.TracebackType | None,
) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        _original_excepthook(exc_type, exc_value, exc_traceback)
        return
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_error(tb)
    _original_excepthook(exc_type, exc_value, exc_traceback)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        _original_threading_excepthook(args)
        return
    tb = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    log_error(f"Uncaught exception in thread {args.thread!r}:\n{tb}")
    _original_threading_excepthook(args)


_original_excepthook = sys.excepthook
_original_threading_excepthook = threading.excepthook


def _install_exception_hooks() -> None:
    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook


def start() -> None:
    """Entry point for the application."""
    _install_exception_hooks()
    log_info("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Shutting down.")
