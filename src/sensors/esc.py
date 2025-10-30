"""ESC sensor interface for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from serial_manager import SerialManager

    from rov_state import RovState

import asyncio
import struct


TELEMETRY_START_BYTE = 0xA5
NUM_MOTORS = 8


class EscSensor:
    """ESC sensor class."""

    def __init__(self, state: RovState, serial_manager: SerialManager):
        """Initialize the ESC sensor.

        Args:
            state: The ROV state.
            serial_manager: The serial manager.
        """
        self.state: RovState = state
        self.serial_manager: SerialManager = serial_manager

    async def read_loop(self) -> None:
        serial = self.serial_manager.get_serial()
        read_buffer = bytearray()
        while True:
            if not self.state.system_health.microcontroller_ok:
                await asyncio.sleep(1)
                continue
            data = await serial.read(1)
            if data:
                read_buffer.extend(data)
                while len(read_buffer) >= 8:
                    start_idx = read_buffer.find(
                        TELEMETRY_START_BYTE.to_bytes(1, "big")
                    )
                    if start_idx == -1:
                        if len(read_buffer) > 16:
                            read_buffer = bytearray()
                        break
                    if start_idx > 0:
                        read_buffer = read_buffer[start_idx:]
                    if len(read_buffer) >= 8:
                        packet = read_buffer[:8]
                        if self._validate_telemetry_packet(packet):
                            self._update_telemetry(packet)
                        read_buffer = read_buffer[8:]
                    else:
                        break

    def _validate_telemetry_packet(self, packet: bytearray) -> bool:
        if len(packet) != 8 or packet[0] != TELEMETRY_START_BYTE:
            return False
        calculated_checksum = 0
        for b in packet[:7]:
            calculated_checksum ^= b
        return calculated_checksum == packet[7]

    def _update_telemetry(self, packet: bytearray) -> None:
        global_id = packet[1]
        packet_type = packet[2]
        value = struct.unpack("<i", packet[3:7])[0]
        if 0 <= global_id < 8:
            if packet_type == 0:
                erpm = list(self.state.esc.erpm)
                erpm[global_id] = value
                self.state.esc.erpm = tuple(erpm)
            elif packet_type == 1:
                voltage = list(self.state.esc.voltage_cv)
                voltage[global_id] = value
                self.state.esc.voltage_cv = tuple(voltage)
            elif packet_type == 2:
                temp = list(self.state.esc.temperature)
                temp[global_id] = value
                self.state.esc.temperature = tuple(temp)
            elif packet_type == 3:
                current = list(self.state.esc.current_ca)
                current[global_id] = value
                self.state.esc.current_ca = tuple(current)
