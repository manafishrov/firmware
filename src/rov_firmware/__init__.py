"""ROV Firmware Package Initialization.

This module exposes the main application entry point and orchestrates
the startup sequence for the ROV firmware.
"""

import asyncio

from .log import log_info
from .main import main


def start() -> None:
    """
    Start the ROV firmware runtime and orchestrate application startup and shutdown.
    
    Runs the package's asynchronous `main()` entrypoint, logs a startup message before execution, suppresses `KeyboardInterrupt` to allow a controlled shutdown, and logs a shutdown message on exit.
    """
    log_info("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Shutting down.")
