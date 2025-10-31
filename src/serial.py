"""Serial communication manager for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rov_state import RovState

import asyncio
from pathlib import Path
import sys

from serial_asyncio import open_serial_connection

from .log import log_error


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

    async def _find_microcontroller_port(self) -> str:
        microcontroller_ports = list(
            Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*")
        )
        if not microcontroller_ports:
            microcontroller_ports = list(Path("/dev/").glob("ttyACM*"))
        if microcontroller_ports:
            return str(microcontroller_ports[0])
        else:
            log_error("Error: Could not find microcontroller serial port.")
            sys.exit(1)

    async def initialize(self) -> None:
        """Initialize the serial connection to the microcontroller."""
        serial_port = await self._find_microcontroller_port()
        self.reader, self.writer = await open_serial_connection(
            url=serial_port, baudrate=115200
        )
        self.state.system_health.microcontroller_ok = True

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
