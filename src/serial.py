from __future__ import annotations
import glob
import sys
from serial.aio import Serial
from .log import log_error


class SerialManager:
    def __init__(self):
        self.serial: Serial | None = None

    async def _find_pico_port(self) -> str:
        pico_ports = glob.glob("/dev/serial/by-id/usb-Raspberry_Pi_Pico*")
        if not pico_ports:
            pico_ports = glob.glob("/dev/ttyACM*")
        if pico_ports:
            return pico_ports[0]
        else:
            log_error("Error: Could not find Raspberry Pi Pico serial port.")
            sys.exit(1)

    async def initialize(self) -> None:
        serial_port = await self._find_pico_port()
        self.serial = Serial(serial_port, baudrate=115200)
        await self.serial.open()

    def get_serial(self) -> Serial:
        if self.serial is None:
            raise RuntimeError("Serial not initialized")
        return self.serial

    async def shutdown(self) -> None:
        if self.serial:
            await self.serial.close()
