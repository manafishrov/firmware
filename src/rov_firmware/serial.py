"""Serial communication manager for the ROV firmware."""

from __future__ import annotations

import asyncio
from pathlib import Path

from serial_asyncio_fast import open_serial_connection

from .log import log_error, log_info
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

    async def _find_microcontroller_port(self) -> str | None:
        microcontroller_ports = list(
            Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*")
        )
        if not microcontroller_ports:
            microcontroller_ports = list(Path("/dev/").glob("ttyACM*"))
        if microcontroller_ports:
            return str(microcontroller_ports[0])
        else:
            log_error("Error: Could not find microcontroller serial port.")
            return None

    async def initialize(self) -> None:
        """Initialize the serial connection to the microcontroller."""
        try:
            log_info("Attempting to initialize serial connection to microcontroller...")
            serial_port = await self._find_microcontroller_port()
            if serial_port is None:
                self.state.system_health.microcontroller_ok = False
                log_error("Failed to find microcontroller serial port.")
                toast_error(
                    toast_id=None,
                    message="Microcontroller Connection Failed!",
                    description="Could not find microcontroller serial port.",
                    cancel=None,
                )
                return
            self.reader, self.writer = await open_serial_connection(
                url=serial_port, baudrate=115200
            )
            self.state.system_health.microcontroller_ok = True
            log_info("Serial connection to microcontroller initialized successfully.")
        except Exception as e:
            self.state.system_health.microcontroller_ok = False
            log_error(
                f"Failed to initialize serial connection to microcontroller. Error: {e}"
            )
            toast_error(
                toast_id=None,
                message="Microcontroller Init Failed!",
                description="Failed to connect to microcontroller. Check connections.",
                cancel=None,
            )

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
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.state.system_health.microcontroller_ok = False
