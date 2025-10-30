"""Serial communication manager for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rov_state import RovState

import glob
import sys

from serial.aio import Serial

from .log import log_error


class SerialManager:
    """Serial manager class."""

    def __init__(self, state: RovState):
        """Initialize the serial manager.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.serial: Serial | None = None

    async def _find_microcontroller_port(self) -> str:
        microcontroller_ports = glob.glob("/dev/serial/by-id/usb-Raspberry_Pi_Pico*")
        if not microcontroller_ports:
            microcontroller_ports = glob.glob("/dev/ttyACM*")
        if microcontroller_ports:
            return microcontroller_ports[0]
        else:
            log_error("Error: Could not find microcontroller serial port.")
            sys.exit(1)

    async def initialize(self) -> None:
        serial_port = await self._find_microcontroller_port()
        self.serial = Serial(serial_port, baudrate=115200)
        await self.serial.open()
        self.state.system_health.microcontroller_ok = True

    def get_serial(self) -> Serial:
        if self.serial is None:
            msg = "Serial not initialized"
            raise RuntimeError(msg)
        return self.serial

    async def shutdown(self) -> None:
        if self.serial:
            await self.serial.close()
        self.state.system_health.microcontroller_ok = False
