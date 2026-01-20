"""ROV Firmware Package Initialization.

This module exposes the main application entry point and orchestrates
the startup sequence for the ROV firmware.
"""

import asyncio

from .log import log_info
from .main import main


def start() -> None:
    """Entry point for the application."""
    log_info("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Shutting down.")
