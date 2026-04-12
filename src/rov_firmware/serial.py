"""Serial communication manager for the ROV firmware."""

import asyncio
import contextlib
from pathlib import Path

from serial_asyncio_fast import open_serial_connection

from .log import log_error, log_info
from .models.toast import ToastContent
from .rov_state import RovState
from .toast import toast_error


class SerialManager:
    """Serial manager class."""

    def __init__(self, state: RovState):
        """Initialize the serial manager.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._connection_lock: asyncio.Lock = asyncio.Lock()

    async def _find_microcontroller_port(
        self, *, log_missing: bool = True
    ) -> str | None:
        microcontroller_ports = list(
            Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*")
        )
        if not microcontroller_ports:
            microcontroller_ports = list(Path("/dev/").glob("ttyACM*"))
        if microcontroller_ports:
            return str(microcontroller_ports[0])
        if log_missing:
            log_error("Error: Could not find microcontroller serial port.")
        return None

    async def _clear_connection_unlocked(self) -> None:
        writer = self.writer
        self.reader = None
        self.writer = None
        self.state.system_health.microcontroller_healthy = False
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def initialize(self, *, notify: bool = True) -> bool:
        """Initialize the serial connection to the microcontroller."""
        async with self._connection_lock:
            if self.reader is not None and self.writer is not None:
                self.state.system_health.microcontroller_healthy = True
                return True

            try:
                if notify:
                    log_info("Attempting to initialize microcontroller...")
                serial_port = await self._find_microcontroller_port(log_missing=notify)
                if serial_port is None:
                    await self._clear_connection_unlocked()
                    if notify:
                        log_error(
                            "Failed to initialize microcontroller. Is it connected?"
                        )
                        toast_error(
                            identifier=None,
                            content=ToastContent(
                                message_key="toasts_microcontroller_init_failed",
                                description_key="toasts_microcontroller_init_failed_description",
                            ),
                            action=None,
                        )
                    return False
                self.reader, self.writer = await open_serial_connection(
                    url=serial_port, baudrate=115200
                )
                self.state.system_health.microcontroller_healthy = True
                log_info("Microcontroller initialized successfully.")
                return True
            except Exception as e:
                await self._clear_connection_unlocked()
                log_error(
                    f"Failed to initialize microcontroller. Is it connected? Error: {e}"
                )
                if notify:
                    toast_error(
                        identifier=None,
                        content=ToastContent(
                            message_key="toasts_microcontroller_init_failed",
                            description_key="toasts_microcontroller_init_failed_description",
                        ),
                        action=None,
                    )
                return False

    async def ensure_connection(self) -> bool:
        """Return whether the microcontroller serial connection is ready for use."""
        if self.state.microcontroller_flashing:
            return False
        if self.reader is not None and self.writer is not None:
            self.state.system_health.microcontroller_healthy = True
            return True
        return await self.initialize(notify=False)

    async def handle_connection_lost(self, reason: str) -> None:
        """Log a serial failure and clear the active microcontroller connection."""
        async with self._connection_lock:
            if self.reader is None and self.writer is None:
                self.state.system_health.microcontroller_healthy = False
                return
            if not self.state.microcontroller_flashing:
                log_error(reason)
            await self._clear_connection_unlocked()

    def get_reader(self) -> asyncio.StreamReader:
        """Get the serial reader."""
        if self.reader is None:
            msg = "Serial not initialized"
            raise RuntimeError(msg)
        return self.reader

    def get_writer(self) -> asyncio.StreamWriter:
        """Get the serial writer."""
        if self.writer is None:
            msg = "Serial not initialized"
            raise RuntimeError(msg)
        return self.writer

    async def shutdown(self) -> None:
        """Shutdown the serial connection."""
        async with self._connection_lock:
            await self._clear_connection_unlocked()
