"""MCU sensor interface for the ROV firmware."""

import asyncio
import struct
import time

from ..constants import (
    ESC_FIRMWARE_VERSION_MAX_LENGTH,
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    LOG_PACKET_HEADER_SIZE,
    LOG_PACKET_START_BYTE,
    MCU_AUTO_UPDATE_WINDOW_S,
    MCU_PROTOCOL_DSHOT,
    MCU_PROTOCOL_PWM,
    MCU_RELEASE_VERSION_MAX_LENGTH,
    MCU_RELEASE_VERSION_PACKET_OVERHEAD,
    MCU_RELEASE_VERSION_START_BYTE,
    MCU_RUNTIME_CONFIG_STATUS_PACKET_SIZE,
    MCU_RUNTIME_CONFIG_STATUS_START_BYTE,
    MCU_SERIAL_READ_TIMEOUT_S,
    MCU_TELEMETRY_BATCH_ENTRY_SIZE,
    MCU_TELEMETRY_BATCH_MAX_ITEMS,
    MCU_TELEMETRY_BATCH_START_BYTE,
    MCU_TELEMETRY_PACKET_SIZE,
    MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE,
    MCU_TELEMETRY_STALE_TIMEOUT_S,
    MCU_TELEMETRY_START_BYTE,
    MCU_TELEMETRY_TYPE_CURRENT,
    MCU_TELEMETRY_TYPE_ERPM,
    MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK,
    MCU_TELEMETRY_TYPE_ESC_VERSION_COMPLETE,
    MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH,
    MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
    MCU_TELEMETRY_TYPE_TEMPERATURE,
    MCU_TELEMETRY_TYPE_VOLTAGE,
    NUM_MOTORS,
)
from ..esc_firmware import is_valid_esc_firmware_version
from ..log import log_error, log_info, log_warn
from ..models.config import ThrusterProtocol
from ..models.log import LogLevel, LogOrigin
from ..models.system import EscFirmwareUpdateStage
from ..rov_state import RovState
from ..serial import SerialManager
from ..version import is_valid_semver
from ..websocket.receive.mcu import (
    flash_mcu_firmware,
    mcu_update_required,
    resolve_mcu_firmware,
)


_MAX_READ_BUFFER_SIZE = 512
_READ_CHUNK_SIZE = 128
_TELEMETRY_BATCH_MIN_PACKET_SIZE = 3
_TELEMETRY_START_TOKEN = bytes((MCU_TELEMETRY_START_BYTE,))
_TELEMETRY_BATCH_START_TOKEN = bytes((MCU_TELEMETRY_BATCH_START_BYTE,))
_LOG_PACKET_START_TOKEN = bytes((LOG_PACKET_START_BYTE,))
_RUNTIME_CONFIG_STATUS_PACKET_START_TOKEN = bytes(
    (MCU_RUNTIME_CONFIG_STATUS_START_BYTE,)
)
_RELEASE_VERSION_PACKET_START_TOKEN = bytes((MCU_RELEASE_VERSION_START_BYTE,))
_TELEMETRY_FIELDS = ("erpm", "voltage", "temperature", "current", "signal_quality")
_ESC_VERSION_TYPES = (
    MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH,
    MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK,
    MCU_TELEMETRY_TYPE_ESC_VERSION_COMPLETE,
)


def _esc_version_crc8(version: bytes) -> int:
    crc = len(version)
    for _ in range(8):
        crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    for value in version:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


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
        self._last_telemetry_time: list[list[float]] = [
            [0.0] * len(_TELEMETRY_FIELDS) for _ in range(NUM_MOTORS)
        ]
        self._startup_time: float = time.monotonic()
        self._flash_task: asyncio.Task[None] | None = None
        self._mcu_auto_flash_attempted = False
        self._esc_version_lengths: list[int | None] = [None] * NUM_MOTORS
        self._esc_version_buffers: list[bytearray] = [
            bytearray() for _ in range(NUM_MOTORS)
        ]
        self._esc_version_next_chunks: list[int] = [0] * NUM_MOTORS
        self._invalid_release_warning_generation = -1
        self._warned_invalid_release_versions: set[str] = set()

    async def read_loop(self) -> None:
        """Read telemetry data from the MCU in a loop."""
        read_buffer = bytearray()
        while True:
            data = await self._read_chunk()
            self._expire_stale_telemetry()
            if data is None:
                await asyncio.sleep(1)
                continue
            self._consume_read_buffer(read_buffer, data)

    async def _read_chunk(self) -> bytes | None:
        if not await self.serial_manager.ensure_connection():
            return None

        async with self.serial_manager.io_lock:
            if self.state.mcu_flashing:
                return None
            reader = self.serial_manager.get_reader()
            try:
                data = await asyncio.wait_for(
                    reader.read(_READ_CHUNK_SIZE), timeout=MCU_SERIAL_READ_TIMEOUT_S
                )
            except TimeoutError:
                return b""
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

    def _consume_next_packet(
        self, read_buffer: bytearray, start_idx: int
    ) -> int | None:
        packet_type = read_buffer[start_idx]
        if packet_type == MCU_TELEMETRY_BATCH_START_BYTE:
            return self._try_consume_telemetry_batch(read_buffer, start_idx)
        if packet_type == MCU_TELEMETRY_START_BYTE:
            return self._try_consume_telemetry(read_buffer, start_idx)
        if packet_type == LOG_PACKET_START_BYTE:
            return self._try_consume_log(read_buffer, start_idx)
        if packet_type == MCU_RUNTIME_CONFIG_STATUS_START_BYTE:
            return self._try_consume_runtime_config_status(read_buffer, start_idx)
        if packet_type == MCU_RELEASE_VERSION_START_BYTE:
            return self._try_consume_release_version(read_buffer, start_idx)
        return start_idx + 1

    def _try_consume_telemetry(
        self, read_buffer: bytearray, start_idx: int
    ) -> int | None:
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

    def _try_consume_runtime_config_status(
        self, read_buffer: bytearray, start_idx: int
    ) -> int | None:
        end_idx = start_idx + MCU_RUNTIME_CONFIG_STATUS_PACKET_SIZE
        if len(read_buffer) < end_idx:
            return None
        packet = memoryview(read_buffer)[start_idx:end_idx]
        if self._validate_runtime_config_status_packet(packet):
            self._handle_runtime_config_status_packet(packet)
        return end_idx

    def _try_consume_release_version(
        self, read_buffer: bytearray, start_idx: int
    ) -> int | None:
        header_end_idx = start_idx + 2
        if len(read_buffer) < header_end_idx:
            return None
        version_length = read_buffer[start_idx + 1]
        if version_length == 0 or version_length > MCU_RELEASE_VERSION_MAX_LENGTH:
            return start_idx + 1
        end_idx = start_idx + version_length + MCU_RELEASE_VERSION_PACKET_OVERHEAD
        if len(read_buffer) < end_idx:
            return None
        packet = memoryview(read_buffer)[start_idx:end_idx]
        if self._validate_release_version_packet(packet):
            self._handle_release_version_packet(packet)
        return end_idx

    @staticmethod
    def _find_start_byte(buf: bytearray, start: int) -> int:
        candidates = (
            buf.find(_TELEMETRY_START_TOKEN, start),
            buf.find(_TELEMETRY_BATCH_START_TOKEN, start),
            buf.find(_LOG_PACKET_START_TOKEN, start),
            buf.find(_RUNTIME_CONFIG_STATUS_PACKET_START_TOKEN, start),
            buf.find(_RELEASE_VERSION_PACKET_START_TOKEN, start),
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
    def _validate_telemetry_batch_packet(
        packet: bytes | bytearray | memoryview,
    ) -> bool:
        if (
            len(packet) < _TELEMETRY_BATCH_MIN_PACKET_SIZE
            or packet[0] != MCU_TELEMETRY_BATCH_START_BYTE
        ):
            return False

        item_count = packet[1]
        expected_len = _TELEMETRY_BATCH_MIN_PACKET_SIZE + (
            item_count * MCU_TELEMETRY_BATCH_ENTRY_SIZE
        )
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
    def _validate_runtime_config_status_packet(
        packet: bytes | bytearray | memoryview,
    ) -> bool:
        if (
            len(packet) != MCU_RUNTIME_CONFIG_STATUS_PACKET_SIZE
            or packet[0] != MCU_RUNTIME_CONFIG_STATUS_START_BYTE
            or packet[1] not in (MCU_PROTOCOL_PWM, MCU_PROTOCOL_DSHOT)
        ):
            return False
        calculated_checksum = 0
        for b in packet[:-1]:
            calculated_checksum ^= b
        return calculated_checksum == packet[-1]

    @staticmethod
    def _validate_release_version_packet(
        packet: bytes | bytearray | memoryview,
    ) -> bool:
        if len(packet) < MCU_RELEASE_VERSION_PACKET_OVERHEAD:
            return False
        version_length = packet[1]
        if (
            packet[0] != MCU_RELEASE_VERSION_START_BYTE
            or version_length == 0
            or version_length > MCU_RELEASE_VERSION_MAX_LENGTH
            or len(packet) != version_length + MCU_RELEASE_VERSION_PACKET_OVERHEAD
        ):
            return False
        calculated_checksum = 0
        for value in packet[:-1]:
            calculated_checksum ^= value
        return calculated_checksum == packet[-1]

    def _handle_release_version_packet(
        self, packet: bytes | bytearray | memoryview
    ) -> None:
        version_length = packet[1]
        try:
            version = bytes(packet[2 : 2 + version_length]).decode("ascii")
        except UnicodeDecodeError:
            encoded = bytes(packet[2 : 2 + version_length])
            self._warn_invalid_release_version_once(
                f"non-ascii:{encoded.hex()}",
                "MCU reported a non-ASCII release version",
            )
            return
        if not is_valid_semver(version):
            self._warn_invalid_release_version_once(
                f"invalid:{version}",
                f"MCU reported an invalid release version: {version!r}",
            )
            return

        self.state.device_info.mcu_firmware_version = version
        self._auto_update_mcu_if_needed(version, self._get_expected_version())

    def _warn_invalid_release_version_once(self, key: str, message: str) -> None:
        generation = self.serial_manager.connection_generation
        if generation != self._invalid_release_warning_generation:
            self._invalid_release_warning_generation = generation
            self._warned_invalid_release_versions.clear()
        if key in self._warned_invalid_release_versions:
            return
        self._warned_invalid_release_versions.add(key)
        log_warn(message)

    @staticmethod
    def _handle_log_packet(packet: bytes | bytearray | memoryview) -> None:
        level_byte = packet[1]
        msg_len = packet[2]
        message = bytes(packet[3 : 3 + msg_len]).decode("utf-8", errors="replace")

        level = _LOG_LEVEL_MAP.get(level_byte, LogLevel.INFO)
        log_fn = _LOG_FN_MAP[level]
        log_fn(message, origin=LogOrigin.MCU)

    def _handle_runtime_config_status_packet(
        self, packet: bytes | bytearray | memoryview
    ) -> None:
        protocol = (
            ThrusterProtocol.DSHOT
            if packet[1] == MCU_PROTOCOL_DSHOT
            else ThrusterProtocol.PWM
        )
        dshot_speed = packet[2] | (packet[3] << 8)
        acknowledged_config = (protocol.value, dshot_speed)
        protocol_changed = (
            self.serial_manager.mcu_protocol_config != acknowledged_config
        )
        self.serial_manager.record_mcu_protocol_config(*acknowledged_config)

        if protocol_changed:
            self._reset_telemetry()

    def _auto_update_window_open(self) -> bool:
        return time.monotonic() - self._startup_time <= MCU_AUTO_UPDATE_WINDOW_S

    def _get_expected_version(self) -> str | None:
        resolved = resolve_mcu_firmware(self.state.rov_config.mcu_board)
        if resolved is None:
            return None
        return resolved[1]

    def _auto_update_mcu_if_needed(
        self, current_version: str, expected_version: str | None
    ) -> None:
        if expected_version is None:
            return

        if not mcu_update_required(current_version, expected_version):
            return

        if self.state.mcu_flashing:
            return

        if self._flash_task is not None and not self._flash_task.done():
            return

        if self._mcu_auto_flash_attempted:
            return

        if not self._auto_update_window_open():
            log_warn(
                f"MCU firmware mismatch ({current_version} != {expected_version}) detected, "
                f"but skipping auto-flash because the service has been running for more than {MCU_AUTO_UPDATE_WINDOW_S} seconds."
            )
            return

        log_warn(
            f"MCU firmware mismatch: current is {current_version}, expected is {expected_version}. Auto-flashing."
        )
        self._mcu_auto_flash_attempted = True
        self._flash_task = asyncio.get_running_loop().create_task(self._flash_mcu())

    async def _flash_mcu(self) -> None:
        succeeded = await flash_mcu_firmware(
            self.state,
            self.state.rov_config.mcu_board,
            show_toasts=True,
        )
        if not succeeded:
            log_error("Auto-flash of MCU firmware failed.")

    def _reset_telemetry(self) -> None:
        for i in range(NUM_MOTORS):
            for packet_type in range(len(_TELEMETRY_FIELDS)):
                self._clear_telemetry_item(i, packet_type)
        self._esc_version_lengths = [None] * NUM_MOTORS
        self._esc_version_buffers = [bytearray() for _ in range(NUM_MOTORS)]
        self._esc_version_next_chunks = [0] * NUM_MOTORS
        self.state.device_info.esc_firmware_versions = [None] * NUM_MOTORS

    def _expire_stale_telemetry(self) -> None:
        now = time.monotonic()
        for i in range(NUM_MOTORS):
            for packet_type, updated_at in enumerate(self._last_telemetry_time[i]):
                if updated_at > 0 and now - updated_at > MCU_TELEMETRY_STALE_TIMEOUT_S:
                    self._clear_telemetry_item(i, packet_type)

    def _clear_telemetry_item(self, global_id: int, packet_type: int) -> None:
        field = _TELEMETRY_FIELDS[packet_type]
        getattr(self.state.mcu_telemetry, field)[global_id] = 0
        if packet_type == MCU_TELEMETRY_TYPE_CURRENT:
            self.state.mcu_telemetry.current_valid[global_id] = False
        elif packet_type == MCU_TELEMETRY_TYPE_SIGNAL_QUALITY:
            self.state.mcu_telemetry.signal_quality_valid[global_id] = False
        self._last_telemetry_time[global_id][packet_type] = 0.0

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

    def _update_telemetry_item(
        self, global_id: int, packet_type: int, value: int
    ) -> None:
        if 0 <= global_id < NUM_MOTORS and packet_type in _ESC_VERSION_TYPES:
            self._update_esc_firmware_version(global_id, packet_type, value)
            return
        if 0 <= global_id < NUM_MOTORS and 0 <= packet_type < len(_TELEMETRY_FIELDS):
            self._last_telemetry_time[global_id][packet_type] = time.monotonic()
            if packet_type == MCU_TELEMETRY_TYPE_ERPM:
                self.state.mcu_telemetry.erpm[global_id] = value * 100
            elif packet_type == MCU_TELEMETRY_TYPE_VOLTAGE:
                self.state.mcu_telemetry.voltage[global_id] = value * 0.25
            elif packet_type == MCU_TELEMETRY_TYPE_TEMPERATURE:
                self.state.mcu_telemetry.temperature[global_id] = value
            elif packet_type == MCU_TELEMETRY_TYPE_CURRENT:
                # EDT current is already in whole amperes. Preserve the raw reading
                # here so changing the configured sensor topology cannot leave a mix
                # of divided and undivided samples in state. Shared-bus de-duplication
                # belongs at aggregation time.
                self.state.mcu_telemetry.current[global_id] = max(0, value)
                self.state.mcu_telemetry.current_valid[global_id] = True
            elif packet_type == MCU_TELEMETRY_TYPE_SIGNAL_QUALITY:
                if value == MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE:
                    self.state.mcu_telemetry.signal_quality[global_id] = 0.0
                    self.state.mcu_telemetry.signal_quality_valid[global_id] = False
                else:
                    self.state.mcu_telemetry.signal_quality[global_id] = value / 100
                    self.state.mcu_telemetry.signal_quality_valid[global_id] = True

    def _update_esc_firmware_version(
        self, global_id: int, packet_type: int, value: int
    ) -> None:
        if packet_type == MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH:
            self._begin_esc_version(global_id, value)
        elif packet_type == MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK:
            self._append_esc_version_chunk(global_id, value)
        else:
            self._complete_esc_version(global_id, value)

    def _begin_esc_version(self, global_id: int, length: int) -> None:
        if not 0 < length <= ESC_FIRMWARE_VERSION_MAX_LENGTH:
            self._reset_esc_version_assembly(global_id)
            return
        self._esc_version_lengths[global_id] = length
        self._esc_version_buffers[global_id].clear()
        self._esc_version_next_chunks[global_id] = 0

    def _append_esc_version_chunk(self, global_id: int, value: int) -> None:
        length = self._esc_version_lengths[global_id]
        if length is None:
            return
        packed = value & 0xFFFFFFFF
        chunk_index = packed >> 24
        if chunk_index != self._esc_version_next_chunks[global_id]:
            self._reset_esc_version_assembly(global_id)
            return
        remaining = length - len(self._esc_version_buffers[global_id])
        chunk = packed.to_bytes(4, "little")[: min(3, remaining)]
        self._esc_version_buffers[global_id].extend(chunk)
        self._esc_version_next_chunks[global_id] += 1

    def _complete_esc_version(self, global_id: int, checksum: int) -> None:
        length = self._esc_version_lengths[global_id]
        if length is None:
            return
        encoded = bytes(self._esc_version_buffers[global_id])
        if len(encoded) != length or checksum != _esc_version_crc8(encoded):
            self._reset_esc_version_assembly(global_id)
            return
        try:
            version = encoded.decode("ascii")
        except UnicodeDecodeError:
            self._reset_esc_version_assembly(global_id)
            return
        if not is_valid_esc_firmware_version(version):
            self._reset_esc_version_assembly(global_id)
            return

        versions = list(self.state.device_info.esc_firmware_versions)
        if versions[global_id] != version:
            versions[global_id] = version
            self.state.device_info.esc_firmware_versions = versions
        self._reset_esc_version_assembly(global_id)
        if all(item is not None for item in versions):
            update = self.state.esc_firmware_update
            if (
                update.stage == EscFirmwareUpdateStage.AWAITING_TELEMETRY
                and update.target_version is not None
                and all(item == update.target_version for item in versions)
            ):
                update.stage = EscFirmwareUpdateStage.SUCCEEDED

    def _reset_esc_version_assembly(self, global_id: int) -> None:
        self._esc_version_lengths[global_id] = None
        self._esc_version_buffers[global_id].clear()
        self._esc_version_next_chunks[global_id] = 0
