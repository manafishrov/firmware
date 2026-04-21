"""MCU sensor interface for the ROV firmware."""

import asyncio
import struct
import time

from ..constants import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    LOG_PACKET_HEADER_SIZE,
    LOG_PACKET_START_BYTE,
    MCU_TELEMETRY_BATCH_ENTRY_SIZE,
    MCU_TELEMETRY_BATCH_MAX_ITEMS,
    MCU_TELEMETRY_BATCH_START_BYTE,
    MCU_PROTOCOL_DSHOT,
    MCU_TELEMETRY_PACKET_SIZE,
    MCU_TELEMETRY_STALE_TIMEOUT_S,
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
from ..websocket.receive.mcu import flash_mcu_firmware, resolve_mcu_firmware


_MAX_READ_BUFFER_SIZE = 512
_READ_CHUNK_SIZE = 128
_TELEMETRY_START_TOKEN = bytes((MCU_TELEMETRY_START_BYTE,))
_TELEMETRY_BATCH_START_TOKEN = bytes((MCU_TELEMETRY_BATCH_START_BYTE,))
_LOG_PACKET_START_TOKEN = bytes((LOG_PACKET_START_BYTE,))
_VERSION_PACKET_START_TOKEN = bytes((MCU_VERSION_START_BYTE,))

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
        self._last_telemetry_time: list[float] = [0.0] * NUM_MOTORS

    async def read_loop(self) -> None:
        """Read telemetry data from the MCU in a loop."""
        read_buffer = bytearray()
        while True:
            data = await self._read_chunk()
            if data is None:
                await asyncio.sleep(1)
                continue
            self._consume_read_buffer(read_buffer, data)
            self._expire_stale_telemetry()

    async def _read_chunk(self) -> bytes | None:
        if not await self.serial_manager.ensure_connection():
            return None

        reader = self.serial_manager.get_reader()
        try:
            data = await reader.read(_READ_CHUNK_SIZE)
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
        search_start = 0

        while True:
            start_idx = self._find_start_byte(read_buffer, search_start)
            if start_idx == -1:
                if search_start > 0:
                    del read_buffer[:search_start]
                if len(read_buffer) > _MAX_READ_BUFFER_SIZE:
                    read_buffer.clear()
                return

            next_idx = self._consume_next_packet(read_buffer, start_idx)
            if next_idx is None:
                if start_idx > 0:
                    del read_buffer[:start_idx]
                return
            search_start = next_idx

            if search_start >= len(read_buffer):
                read_buffer.clear()
                return

    def _consume_next_packet(self, read_buffer: bytearray, start_idx: int) -> int | None:
        packet_type = read_buffer[start_idx]
        if packet_type == MCU_TELEMETRY_BATCH_START_BYTE:
            return self._try_consume_telemetry_batch(read_buffer, start_idx)
        if packet_type == MCU_TELEMETRY_START_BYTE:
            return self._try_consume_telemetry(read_buffer, start_idx)
        if packet_type == LOG_PACKET_START_BYTE:
            return self._try_consume_log(read_buffer, start_idx)
        if packet_type == MCU_VERSION_START_BYTE:
            return self._try_consume_version(read_buffer, start_idx)
        return start_idx + 1

    def _try_consume_telemetry(self, read_buffer: bytearray, start_idx: int) -> int | None:
        end_idx = start_idx + MCU_TELEMETRY_PACKET_SIZE
        if len(read_buffer) < end_idx:
            return None

        packet = memoryview(read_buffer)[start_idx:end_idx]
        if self._validate_telemetry_packet(packet):
            self._update_telemetry(packet)
        return end_idx

    def _try_consume_telemetry_batch(
        self, read_buffer: bytearray, start_idx: int
    ) -> int | None:
        if len(read_buffer) < start_idx + 2:
            return None

        item_count = read_buffer[start_idx + 1]
        if item_count == 0 or item_count > MCU_TELEMETRY_BATCH_MAX_ITEMS:
            return start_idx + 1

        end_idx = start_idx + 3 + (item_count * MCU_TELEMETRY_BATCH_ENTRY_SIZE)
        if len(read_buffer) < end_idx:
            return None

        packet = memoryview(read_buffer)[start_idx:end_idx]
        if self._validate_telemetry_batch_packet(packet):
            self._update_telemetry_batch(packet)
        return end_idx

    @staticmethod
    def _try_consume_log(read_buffer: bytearray, start_idx: int) -> int | None:
        header_end_idx = start_idx + LOG_PACKET_HEADER_SIZE
        if len(read_buffer) < header_end_idx:
            return None
        msg_len = read_buffer[start_idx + 2]
        end_idx = header_end_idx + msg_len + 1
        if len(read_buffer) < end_idx:
            return None
        packet = memoryview(read_buffer)[start_idx:end_idx]
        if McuSensor._validate_log_packet(packet):
            McuSensor._handle_log_packet(packet)
        return end_idx

    def _try_consume_version(self, read_buffer: bytearray, start_idx: int) -> int | None:
        end_idx = start_idx + MCU_VERSION_PACKET_SIZE
        if len(read_buffer) < end_idx:
            return None
        packet = memoryview(read_buffer)[start_idx:end_idx]
        if self._validate_version_packet(packet):
            self._handle_version_packet(packet)
        return end_idx

    @staticmethod
    def _find_start_byte(buf: bytearray, start: int) -> int:
        candidates = (
            buf.find(_TELEMETRY_START_TOKEN, start),
            buf.find(_TELEMETRY_BATCH_START_TOKEN, start),
            buf.find(_LOG_PACKET_START_TOKEN, start),
            buf.find(_VERSION_PACKET_START_TOKEN, start),
        )
        valid_candidates = [idx for idx in candidates if idx >= 0]
        if not valid_candidates:
            return -1
        return min(valid_candidates)

    @staticmethod
    def _validate_telemetry_packet(packet: bytes | bytearray | memoryview) -> bool:
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
    def _validate_telemetry_batch_packet(packet: bytes | bytearray | memoryview) -> bool:
        if len(packet) < 3 or packet[0] != MCU_TELEMETRY_BATCH_START_BYTE:
            return False

        item_count = packet[1]
        expected_len = 3 + (item_count * MCU_TELEMETRY_BATCH_ENTRY_SIZE)
        if item_count == 0 or item_count > MCU_TELEMETRY_BATCH_MAX_ITEMS:
            return False
        if len(packet) != expected_len:
            return False

        calculated_checksum = 0
        for b in packet[:-1]:
            calculated_checksum ^= b
        return calculated_checksum == packet[-1]

    @staticmethod
    def _validate_log_packet(packet: bytes | bytearray | memoryview) -> bool:
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
    def _validate_version_packet(packet: bytes | bytearray | memoryview) -> bool:
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
    def _handle_log_packet(packet: bytes | bytearray | memoryview) -> None:
        level_byte = packet[1]
        msg_len = packet[2]
        message = bytes(packet[3 : 3 + msg_len]).decode("utf-8", errors="replace")

        level = _LOG_LEVEL_MAP.get(level_byte, LogLevel.INFO)
        log_fn = _LOG_FN_MAP[level]
        log_fn(message, origin=LogOrigin.MCU)

    def _handle_version_packet(self, packet: bytes | bytearray | memoryview) -> None:
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
            self._reset_telemetry()
            get_message_queue().put_nowait(Config(payload=self.state.rov_config))

        expected = self._get_expected_version()
        if expected is not None and version != expected:
            self._schedule_version_mismatch_flash(version, expected)

    def _get_expected_version(self) -> str | None:
        resolved = resolve_mcu_firmware(self.state.rov_config.mcu_board)
        if resolved is None:
            return None
        return resolved[1]

    def _schedule_version_mismatch_flash(
        self, current_version: str, expected_version: str
    ) -> None:
        log_warn(
            f"MCU firmware version mismatch: {current_version} != {expected_version}. Auto-flashing..."
        )
        board = self.state.rov_config.mcu_board
        asyncio.get_running_loop().create_task(
            flash_mcu_firmware(self.state, board, show_toasts=True)
        )

    def _reset_telemetry(self) -> None:
        for i in range(NUM_MOTORS):
            self.state.mcu_telemetry.erpm[i] = 0
            self.state.mcu_telemetry.current[i] = 0
            self.state.mcu_telemetry.voltage[i] = 0.0
            self.state.mcu_telemetry.temperature[i] = 0
            self.state.mcu_telemetry.signal_quality[i] = 0.0
            self._last_telemetry_time[i] = 0.0

    def _expire_stale_telemetry(self) -> None:
        now = time.monotonic()
        for i in range(NUM_MOTORS):
            if (
                self._last_telemetry_time[i] > 0
                and now - self._last_telemetry_time[i] > MCU_TELEMETRY_STALE_TIMEOUT_S
            ):
                self.state.mcu_telemetry.erpm[i] = 0
                self.state.mcu_telemetry.current[i] = 0
                self.state.mcu_telemetry.voltage[i] = 0.0
                self.state.mcu_telemetry.temperature[i] = 0
                self.state.mcu_telemetry.signal_quality[i] = 0.0
                self._last_telemetry_time[i] = 0.0

    def _update_telemetry(self, packet: bytes | bytearray | memoryview) -> None:
        """Update MCU telemetry from a validated packet.

        Units: erpm in full eRPM, voltage in volts (0.25V/LSB),
        current in 1A, temperature in °C, signal_quality in %.
        """
        self._update_telemetry_item(
            global_id=packet[1],
            packet_type=packet[2],
            value=struct.unpack_from("<i", packet, 3)[0],
        )

    def _update_telemetry_batch(self, packet: bytes | bytearray | memoryview) -> None:
        item_count = packet[1]
        offset = 2
        for _ in range(item_count):
            global_id = packet[offset]
            packet_type = packet[offset + 1]
            value = struct.unpack_from("<i", packet, offset + 2)[0]
            self._update_telemetry_item(global_id, packet_type, value)
            offset += MCU_TELEMETRY_BATCH_ENTRY_SIZE

    def _update_telemetry_item(self, global_id: int, packet_type: int, value: int) -> None:
        if 0 <= global_id < NUM_MOTORS:
            self._last_telemetry_time[global_id] = time.monotonic()
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
