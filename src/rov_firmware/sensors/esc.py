"""ESC sensor interface for the ROV firmware."""

import asyncio
import struct

from ..constants import (
    ESC_PACKET_TYPE_CURRENT,
    ESC_PACKET_TYPE_ERPM,
    ESC_PACKET_TYPE_SIGNAL_QUALITY,
    ESC_PACKET_TYPE_TEMPERATURE,
    ESC_PACKET_TYPE_VOLTAGE,
    ESC_TELEMETRY_PACKET_SIZE,
    ESC_TELEMETRY_START_BYTE,
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    LOG_PACKET_HEADER_SIZE,
    LOG_PACKET_START_BYTE,
    NUM_MOTORS,
)
from ..log import log_error, log_info, log_warn
from ..models.log import LogLevel, LogOrigin
from ..rov_state import RovState
from ..serial import SerialManager


_MAX_READ_BUFFER_SIZE = 512

_LOG_LEVEL_MAP: dict[int, LogLevel] = {
    LOG_LEVEL_INFO: LogLevel.INFO,
    LOG_LEVEL_WARN: LogLevel.WARN,
    LOG_LEVEL_ERROR: LogLevel.ERROR,
}

_LOG_FN_MAP = {
    LogLevel.INFO: log_info,
    LogLevel.WARN: log_warn,
    LogLevel.ERROR: log_error,
}


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
        read_buffer = bytearray()
        while True:
            data = await self._read_byte()
            if data is None:
                await asyncio.sleep(1)
                continue
            self._consume_read_buffer(read_buffer, data)

    async def _read_byte(self) -> bytes | None:
        if not await self.serial_manager.ensure_connection():
            return None

        reader = self.serial_manager.get_reader()
        try:
            data = await reader.read(1)
        except Exception as e:
            await self.serial_manager.handle_connection_lost(
                f"ESC telemetry read failed, disabling microcontroller. Error: {e}"
            )
            return None

        if not data:
            await self.serial_manager.handle_connection_lost(
                "ESC telemetry stream closed, disabling microcontroller"
            )
            return None

        return data

    def _consume_read_buffer(self, read_buffer: bytearray, data: bytes) -> None:
        read_buffer.extend(data)
        while True:
            start_idx = self._find_start_byte(read_buffer)
            if start_idx == -1:
                if len(read_buffer) > _MAX_READ_BUFFER_SIZE:
                    read_buffer.clear()
                return
            if start_idx > 0:
                del read_buffer[:start_idx]

            if read_buffer[0] == ESC_TELEMETRY_START_BYTE:
                if not self._try_consume_telemetry(read_buffer):
                    return
            elif read_buffer[0] == LOG_PACKET_START_BYTE:
                if not self._try_consume_log(read_buffer):
                    return
            else:
                del read_buffer[:1]

    def _try_consume_telemetry(self, read_buffer: bytearray) -> bool:
        if len(read_buffer) < ESC_TELEMETRY_PACKET_SIZE:
            return False
        packet = read_buffer[:ESC_TELEMETRY_PACKET_SIZE]
        if self._validate_telemetry_packet(packet):
            self._update_telemetry(packet)
        del read_buffer[:ESC_TELEMETRY_PACKET_SIZE]
        return True

    @staticmethod
    def _try_consume_log(read_buffer: bytearray) -> bool:
        if len(read_buffer) < LOG_PACKET_HEADER_SIZE:
            return False
        msg_len = read_buffer[2]
        total_len = LOG_PACKET_HEADER_SIZE + msg_len + 1
        if len(read_buffer) < total_len:
            return False
        packet = read_buffer[:total_len]
        if EscSensor._validate_log_packet(packet):
            EscSensor._handle_log_packet(packet)
        del read_buffer[:total_len]
        return True

    @staticmethod
    def _find_start_byte(buf: bytearray) -> int:
        for i, b in enumerate(buf):
            if b in (ESC_TELEMETRY_START_BYTE, LOG_PACKET_START_BYTE):
                return i
        return -1

    @staticmethod
    def _validate_telemetry_packet(packet: bytearray) -> bool:
        if (
            len(packet) != ESC_TELEMETRY_PACKET_SIZE
            or packet[0] != ESC_TELEMETRY_START_BYTE
        ):
            return False
        calculated_checksum = 0
        for b in packet[:7]:
            calculated_checksum ^= b
        return calculated_checksum == packet[7]

    @staticmethod
    def _validate_log_packet(packet: bytearray) -> bool:
        if (
            len(packet) < LOG_PACKET_HEADER_SIZE + 1
            or packet[0] != LOG_PACKET_START_BYTE
        ):
            return False
        calculated_checksum = 0
        for b in packet[:-1]:
            calculated_checksum ^= b
        return calculated_checksum == packet[-1]

    @staticmethod
    def _handle_log_packet(packet: bytearray) -> None:
        level_byte = packet[1]
        msg_len = packet[2]
        message = packet[3 : 3 + msg_len].decode("utf-8", errors="replace")

        level = _LOG_LEVEL_MAP.get(level_byte, LogLevel.INFO)
        log_fn = _LOG_FN_MAP[level]
        log_fn(message, origin=LogOrigin.MICROCONTROLLER)

    def _update_telemetry(self, packet: bytearray) -> None:
        """Update ESC telemetry data from a validated packet.

        Parses the packet and updates the corresponding motor's telemetry in state.
        Units: erpm in full eRPM, voltage in raw EDT byte (0.25V/LSB),
        current in 1A, temperature in °C, signal_quality in 0.01% valid.
        """
        global_id = packet[1]
        packet_type = packet[2]
        value = struct.unpack("<i", packet[3:7])[0]
        if 0 <= global_id < NUM_MOTORS:
            if packet_type == ESC_PACKET_TYPE_ERPM:
                self.state.esc.erpm[global_id] = value * 100  # eRPM/100 to eRPM
            elif packet_type == ESC_PACKET_TYPE_VOLTAGE:
                self.state.esc.voltage[global_id] = (
                    value * 0.25
                )  # raw EDT byte to volts
            elif packet_type == ESC_PACKET_TYPE_TEMPERATURE:
                self.state.esc.temperature[global_id] = value  # °C
            elif packet_type == ESC_PACKET_TYPE_CURRENT:
                self.state.esc.current[global_id] = value  # 1A
            elif packet_type == ESC_PACKET_TYPE_SIGNAL_QUALITY:
                self.state.esc.signal_quality[global_id] = value / 100  # 0.01% to %
