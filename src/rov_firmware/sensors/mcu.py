"""MCU sensor interface for the ROV firmware."""

import asyncio
import struct

from ..constants import (
    EXPECTED_MCU_FIRMWARE_VERSION,
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    LOG_PACKET_HEADER_SIZE,
    LOG_PACKET_START_BYTE,
    MCU_PROTOCOL_DSHOT,
    MCU_TELEMETRY_PACKET_SIZE,
    MCU_TELEMETRY_START_BYTE,
    MCU_TELEMETRY_TYPE_CURRENT,
    MCU_TELEMETRY_TYPE_ERPM,
    MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
    MCU_TELEMETRY_TYPE_TEMPERATURE,
    MCU_TELEMETRY_TYPE_VOLTAGE,
    MCU_VERSION_PACKET_SIZE,
    MCU_VERSION_START_BYTE,
    MOTORS_PER_BUS,
    NUM_MOTORS,
)
from ..log import log_error, log_info, log_warn
from ..models.config import CurrentSensingMode, ThrusterProtocol
from ..models.log import LogLevel, LogOrigin
from ..rov_state import RovState
from ..serial import SerialManager
from ..websocket.message import Config
from ..websocket.queue import get_message_queue


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


class McuSensor:
    """MCU sensor class."""

    def __init__(self, state: RovState, serial_manager: SerialManager):
        """Initialize the MCU sensor.

        Args:
            state: The ROV state.
            serial_manager: The serial manager.
        """
        self.state: RovState = state
        self.serial_manager: SerialManager = serial_manager

    async def read_loop(self) -> None:
        """Read telemetry data from the MCU in a loop."""
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
                f"MCU telemetry read failed, disabling MCU. Error: {e}"
            )
            return None

        if not data:
            await self.serial_manager.handle_connection_lost(
                "MCU telemetry stream closed, disabling MCU"
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

            if not self._consume_next_packet(read_buffer):
                return

    def _consume_next_packet(self, read_buffer: bytearray) -> bool:
        if read_buffer[0] == MCU_TELEMETRY_START_BYTE:
            return self._try_consume_telemetry(read_buffer)
        if read_buffer[0] == LOG_PACKET_START_BYTE:
            return self._try_consume_log(read_buffer)
        if read_buffer[0] == MCU_VERSION_START_BYTE:
            return self._try_consume_version(read_buffer)
        del read_buffer[:1]
        return True

    def _try_consume_telemetry(self, read_buffer: bytearray) -> bool:
        if len(read_buffer) < MCU_TELEMETRY_PACKET_SIZE:
            return False
        packet = read_buffer[:MCU_TELEMETRY_PACKET_SIZE]
        if self._validate_telemetry_packet(packet):
            self._update_telemetry(packet)
        del read_buffer[:MCU_TELEMETRY_PACKET_SIZE]
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
        if McuSensor._validate_log_packet(packet):
            McuSensor._handle_log_packet(packet)
        del read_buffer[:total_len]
        return True

    def _try_consume_version(self, read_buffer: bytearray) -> bool:
        if len(read_buffer) < MCU_VERSION_PACKET_SIZE:
            return False
        packet = read_buffer[:MCU_VERSION_PACKET_SIZE]
        if self._validate_version_packet(packet):
            self._handle_version_packet(packet)
        del read_buffer[:MCU_VERSION_PACKET_SIZE]
        return True

    @staticmethod
    def _find_start_byte(buf: bytearray) -> int:
        for i, b in enumerate(buf):
            if b in (
                MCU_TELEMETRY_START_BYTE,
                LOG_PACKET_START_BYTE,
                MCU_VERSION_START_BYTE,
            ):
                return i
        return -1

    @staticmethod
    def _validate_telemetry_packet(packet: bytearray) -> bool:
        if (
            len(packet) != MCU_TELEMETRY_PACKET_SIZE
            or packet[0] != MCU_TELEMETRY_START_BYTE
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
    def _validate_version_packet(packet: bytearray) -> bool:
        if (
            len(packet) != MCU_VERSION_PACKET_SIZE
            or packet[0] != MCU_VERSION_START_BYTE
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
        log_fn(message, origin=LogOrigin.MCU)

    def _handle_version_packet(self, packet: bytearray) -> None:
        version = f"{packet[1]}.{packet[2]}.{packet[3]}"
        protocol = (
            ThrusterProtocol.DSHOT
            if packet[4] == MCU_PROTOCOL_DSHOT
            else ThrusterProtocol.PWM
        )
        dshot_speed = packet[5] | (packet[6] << 8)

        changed = (
            self.state.rov_config.mcu_firmware_version != version
            or self.state.rov_config.thruster_protocol != protocol
            or self.state.rov_config.dshot_speed != dshot_speed
        )

        self.state.rov_config.mcu_firmware_version = version
        self.state.rov_config.thruster_protocol = protocol
        self.state.rov_config.dshot_speed = dshot_speed

        if changed:
            get_message_queue().put_nowait(Config(payload=self.state.rov_config))

        if version != EXPECTED_MCU_FIRMWARE_VERSION:
            self._schedule_version_mismatch_flash(version)

    def _schedule_version_mismatch_flash(self, current_version: str) -> None:
        import asyncio  # noqa: PLC0415

        from ..websocket.receive.mcu import flash_mcu_firmware  # noqa: PLC0415

        log_warn(
            f"MCU firmware version mismatch: {current_version} != {EXPECTED_MCU_FIRMWARE_VERSION}. Auto-flashing..."
        )
        board = self.state.rov_config.mcu_board
        asyncio.get_running_loop().create_task(
            flash_mcu_firmware(self.state, board, show_toasts=True)
        )

    def _update_telemetry(self, packet: bytearray) -> None:
        """Update MCU telemetry from a validated packet.

        Units: erpm in full eRPM, voltage in volts (0.25V/LSB),
        current in 1A, temperature in °C, signal_quality in %.
        """
        global_id = packet[1]
        packet_type = packet[2]
        value = struct.unpack("<i", packet[3:7])[0]
        if 0 <= global_id < NUM_MOTORS:
            if packet_type == MCU_TELEMETRY_TYPE_ERPM:
                self.state.mcu_telemetry.erpm[global_id] = value * 100
            elif packet_type == MCU_TELEMETRY_TYPE_VOLTAGE:
                self.state.mcu_telemetry.voltage[global_id] = value * 0.25
            elif packet_type == MCU_TELEMETRY_TYPE_TEMPERATURE:
                self.state.mcu_telemetry.temperature[global_id] = value
            elif packet_type == MCU_TELEMETRY_TYPE_CURRENT:
                if (
                    self.state.rov_config.current_sensing_mode
                    == CurrentSensingMode.SHARED_BUS
                ):
                    self.state.mcu_telemetry.current[global_id] = (
                        value // MOTORS_PER_BUS
                    )
                else:
                    self.state.mcu_telemetry.current[global_id] = value
            elif packet_type == MCU_TELEMETRY_TYPE_SIGNAL_QUALITY:
                self.state.mcu_telemetry.signal_quality[global_id] = value / 100
