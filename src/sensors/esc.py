"""ESC sensor interface for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from ..models.esc import EscTuple
    from ..rov_state import RovState
    from ..serial import SerialManager

import asyncio
import struct

from ..constants import (
    MAX_READ_BUFFER_SIZE,
    NUM_MOTORS,
    PACKET_TYPE_CURRENT,
    PACKET_TYPE_ERPM,
    PACKET_TYPE_TEMPERATURE,
    PACKET_TYPE_VOLTAGE,
    TELEMETRY_PACKET_SIZE,
    TELEMETRY_START_BYTE,
)


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
        """Read telemetry data from the ESC sensor in a loop."""
        reader = self.serial_manager.get_reader()
        read_buffer = bytearray()
        while True:
            if not self.state.system_health.microcontroller_ok:
                await asyncio.sleep(1)
                continue
            data = await reader.read(1)
            if data:
                read_buffer.extend(data)
                while len(read_buffer) >= TELEMETRY_PACKET_SIZE:
                    start_idx = read_buffer.find(
                        TELEMETRY_START_BYTE.to_bytes(1, "big")
                    )
                    if start_idx == -1:
                        if len(read_buffer) > MAX_READ_BUFFER_SIZE:
                            read_buffer = bytearray()
                        break
                    if start_idx > 0:
                        read_buffer = read_buffer[start_idx:]
                    if len(read_buffer) >= TELEMETRY_PACKET_SIZE:
                        packet = read_buffer[:TELEMETRY_PACKET_SIZE]
                        if self._validate_telemetry_packet(packet):
                            self._update_telemetry(packet)
                        read_buffer = read_buffer[TELEMETRY_PACKET_SIZE:]
                    else:
                        break

    def _validate_telemetry_packet(self, packet: bytearray) -> bool:
        if len(packet) != TELEMETRY_PACKET_SIZE or packet[0] != TELEMETRY_START_BYTE:
            return False
        calculated_checksum = 0
        for b in packet[:7]:
            calculated_checksum ^= b
        return calculated_checksum == packet[7]

    def _update_telemetry(self, packet: bytearray) -> None:
        global_id = packet[1]
        packet_type = packet[2]
        value = cast(int, struct.unpack("<i", packet[3:7])[0])
        if 0 <= global_id < NUM_MOTORS:
            if packet_type == PACKET_TYPE_ERPM:
                erpm = list(self.state.esc.erpm)
                erpm[global_id] = value
                self.state.esc.erpm = cast(EscTuple, tuple(erpm))
            elif packet_type == PACKET_TYPE_VOLTAGE:
                voltage = list(self.state.esc.voltage_cv)
                voltage[global_id] = value
                self.state.esc.voltage_cv = cast(EscTuple, tuple(voltage))
            elif packet_type == PACKET_TYPE_TEMPERATURE:
                temp = list(self.state.esc.temperature)
                temp[global_id] = value
                self.state.esc.temperature = cast(EscTuple, tuple(temp))
            elif packet_type == PACKET_TYPE_CURRENT:
                current = list(self.state.esc.current_ca)
                current[global_id] = value
                self.state.esc.current_ca = cast(EscTuple, tuple(current))
