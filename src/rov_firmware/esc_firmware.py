"""Automatic ESC firmware updates through the thruster MCU."""

import asyncio
from collections.abc import Callable
import contextlib
from enum import IntEnum
from pathlib import Path
import re
import struct
import time
import zlib

from .constants import (
    ESC_FIRMWARE_APPLICATION_ADDRESS,
    ESC_FIRMWARE_EEPROM_ADDRESS,
    ESC_FIRMWARE_FLASH_TOAST_ID,
    ESC_FIRMWARE_IMAGE_SIZE,
    ESC_FIRMWARE_TARGET_F421_PB4_32K,
    ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE,
    ESC_FIRMWARE_USB_CONTROL_START_BYTE,
    ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE,
    ESC_FIRMWARE_USB_DATA_START_BYTE,
    ESC_FIRMWARE_USB_STATUS_PACKET_SIZE,
    ESC_FIRMWARE_USB_STATUS_START_BYTE,
    NUM_MOTORS,
)
from .log import log_error, log_info, log_warn
from .models.config import ThrusterProtocol
from .models.system import EscFirmwareUpdateOrigin, EscFirmwareUpdateStage
from .models.toast import ToastContent
from .rov_state import RovState
from .serial import SerialManager
from .toast import toast_error, toast_loading, toast_success
from .version import is_valid_semver, semver_sort_key


_TARGET_NAME = b"SKYSTARS_AM60_V2_F421"
_RELEASE_MAGIC = b"MANAESC1:"
_ALL_ESCS = 0xFF
_STATUS_TIMEOUT_S = 8.0
_DISARM_SETTLE_S = 0.25
_HEX_RECORD_OVERHEAD = 5
_HEX_DATA = 0
_HEX_EOF = 1
_HEX_EXTENDED_LINEAR_ADDRESS = 4
_HEX_START_LINEAR_ADDRESS = 5
_HEX_EXTENDED_ADDRESS_SIZE = 2
_HEX_START_ADDRESS_SIZE = 4
_SRAM_START = 0x20000000
_SRAM_END = 0x20010000


class _Command(IntEnum):
    BEGIN = 1
    COMMIT = 2
    ABORT = 3


class _Status(IntEnum):
    READY = 1
    RECEIVED = 2
    ENTERING_BOOTLOADER = 3
    MOTOR_BEGIN = 4
    MOTOR_DONE = 5
    COMPLETE = 6
    FAILED = 7
    ABORTED = 8


class _Error(IntEnum):
    NONE = 0
    BAD_PACKET = 1
    NOT_DSHOT = 2
    THRUSTERS_ACTIVE = 3
    INVALID_IMAGE = 4
    BAD_SEQUENCE = 5
    IMAGE_CRC = 6
    BOOTLOADER_CONNECT = 7
    WRONG_TARGET = 8
    PROGRAM = 9
    VERIFY = 10


_ERROR_MESSAGES = {
    _Error.BAD_PACKET: "the Pico received a damaged updater packet",
    _Error.NOT_DSHOT: "DShot is not configured and ready",
    _Error.THRUSTERS_ACTIVE: "the thrusters are not neutral",
    _Error.INVALID_IMAGE: "the firmware image is invalid or targets different hardware",
    _Error.BAD_SEQUENCE: "the firmware upload arrived out of order",
    _Error.IMAGE_CRC: "the uploaded image failed its checksum",
    _Error.BOOTLOADER_CONNECT: "the ESC bootloader did not respond",
    _Error.WRONG_TARGET: "the connected ESC is not the supported F421/PB4 target",
    _Error.PROGRAM: "writing flash failed; the ESCs remain stopped for a safe retry",
    _Error.VERIFY: "flash verification failed; the ESCs remain stopped for a safe retry",
}


class EscFirmwareUpdateError(RuntimeError):
    """Raised when an ESC firmware image or update transaction is invalid."""


def resolve_esc_firmware() -> tuple[Path, str] | None:
    """Return the newest bundled ESC firmware image and its SemVer."""
    firmware_dir = Path.home() / "esc-firmware"
    candidates: list[tuple[Path, str]] = []
    for path in firmware_dir.glob("esc-v*.*"):
        match = re.fullmatch(r"esc-v(.+)\.(?:bin|hex)", path.name)
        if match is not None and is_valid_esc_firmware_version(match.group(1)):
            candidates.append((path, match.group(1)))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            semver_sort_key(candidate[1]),
            candidate[0].suffix == ".bin",
        ),
    )


def is_valid_esc_firmware_version(version: str) -> bool:
    """Return whether a reported ESC release string is valid SemVer."""
    return is_valid_semver(version)


def esc_firmware_update_required(
    version: str, installed_versions: list[str | None]
) -> bool:
    """Return whether any ESC differs from the bundled firmware version."""
    return len(installed_versions) != NUM_MOTORS or any(
        installed != version for installed in installed_versions
    )


def _toast_esc_flash_error(error: str) -> None:
    toast_error(
        identifier=ESC_FIRMWARE_FLASH_TOAST_ID,
        content=ToastContent(
            message_key="toasts_esc_flash_failed",
            description_key="toasts_esc_flash_failed_description",
            description_args={"error": error},
        ),
        action=None,
    )


def _toast_esc_flash_progress(percent: int, motor: int | None) -> None:
    toast_loading(
        identifier=ESC_FIRMWARE_FLASH_TOAST_ID,
        content=ToastContent(
            message_key="toasts_esc_flash_in_progress",
            message_args={"percent": percent},
            description_key=(
                "toasts_esc_flash_uploading"
                if motor is None
                else "toasts_esc_flash_motor_progress"
            ),
            description_args=(
                None if motor is None else {"esc": motor + 1, "total": NUM_MOTORS}
            ),
        ),
        action=None,
    )


class _EscFlashProgress:
    """Publish live update state and deduplicated toast progress."""

    def __init__(self, state: RovState, show_toasts: bool) -> None:
        self._state = state
        self._show_toasts = show_toasts
        self._last_percent = -1
        self._last_motor: int | None = None

    def __call__(self, percent: int, motor: int | None) -> None:
        if percent == self._last_percent and motor == self._last_motor:
            return
        self._last_percent = percent
        self._last_motor = motor
        update = self._state.esc_firmware_update
        update.progress = percent
        update.current_esc = None if motor is None else motor + 1
        update.stage = (
            EscFirmwareUpdateStage.UPLOADING
            if motor is None
            else EscFirmwareUpdateStage.PROGRAMMING
        )
        if self._show_toasts:
            _toast_esc_flash_progress(percent, motor)


def _notify_esc_flash_error(show_toasts: bool, error: str) -> None:
    if show_toasts:
        _toast_esc_flash_error(error)


def _notify_esc_flash_success(show_toasts: bool) -> None:
    if show_toasts:
        toast_success(
            identifier=ESC_FIRMWARE_FLASH_TOAST_ID,
            content=ToastContent(message_key="toasts_esc_flash_success"),
            action=None,
        )


def _format_updater_failure(motor: int, error: int) -> str:
    scope = "ESC firmware updater" if motor == _ALL_ESCS else f"ESC {motor + 1}"
    try:
        updater_error = _Error(error)
    except ValueError:
        return f"{scope} failed with unknown error {error}"
    detail = _ERROR_MESSAGES.get(
        updater_error, "the updater reported an unspecified failure"
    )
    return f"{scope} failed because {detail}"


def _thrusters_idle(state: RovState) -> bool:
    direction = state.thrusters.direction_vector
    no_requested_motion = direction is None or all(
        float(value) == 0.0 for value in direction
    )
    return (
        no_requested_motion
        and state.thrusters.test_thruster is None
        and not state.system_status.auto_stabilization
        and not state.system_status.depth_hold
    )


def _decode_hex_record(line: str, line_number: int) -> tuple[int, int, int, bytes]:
    if not line.startswith(":"):
        msg = f"ESC firmware Intel HEX has an invalid record on line {line_number}"
        raise EscFirmwareUpdateError(msg)
    try:
        record = bytes.fromhex(line[1:])
    except ValueError as error:
        msg = f"ESC firmware Intel HEX contains non-hex data on line {line_number}"
        raise EscFirmwareUpdateError(msg) from error
    if (
        len(record) < _HEX_RECORD_OVERHEAD
        or len(record) != record[0] + _HEX_RECORD_OVERHEAD
        or sum(record) & 0xFF
    ):
        msg = f"ESC firmware Intel HEX checksum/length failed on line {line_number}"
        raise EscFirmwareUpdateError(msg)
    length = record[0]
    address = (record[1] << 8) | record[2]
    return length, address, record[3], record[4 : 4 + length]


def _store_hex_data(
    buffers: tuple[bytearray, bytearray],
    upper_address: int,
    address: int,
    data: bytes,
    line_number: int,
) -> None:
    image, written = buffers
    absolute_address = upper_address + address
    end_address = absolute_address + len(data)
    if (
        absolute_address < ESC_FIRMWARE_APPLICATION_ADDRESS
        or end_address > ESC_FIRMWARE_EEPROM_ADDRESS
    ):
        msg = f"ESC firmware image writes outside the application region on line {line_number}"
        raise EscFirmwareUpdateError(msg)
    offset = absolute_address - ESC_FIRMWARE_APPLICATION_ADDRESS
    if any(written[offset : offset + len(data)]):
        msg = f"ESC firmware Intel HEX overlaps data on line {line_number}"
        raise EscFirmwareUpdateError(msg)
    image[offset : offset + len(data)] = data
    written[offset : offset + len(data)] = b"\x01" * len(data)


def _validate_hex_control_record(
    length: int, address: int, expected_length: int, name: str, line_number: int
) -> None:
    if length != expected_length or address != 0:
        msg = f"ESC firmware Intel HEX has an invalid {name} on line {line_number}"
        raise EscFirmwareUpdateError(msg)


def _parse_intel_hex(path: Path) -> bytes:
    image = bytearray([0xFF]) * ESC_FIRMWARE_IMAGE_SIZE
    written = bytearray(ESC_FIRMWARE_IMAGE_SIZE)
    buffers = (image, written)
    upper_address = 0
    eof_seen = False

    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except OSError as error:
        msg = f"Could not read ESC firmware image: {error}"
        raise EscFirmwareUpdateError(msg) from error

    for line_number, line in enumerate(lines, start=1):
        if eof_seen:
            msg = f"ESC firmware Intel HEX has data after EOF on line {line_number}"
            raise EscFirmwareUpdateError(msg)
        length, address, record_type, data = _decode_hex_record(line, line_number)
        if record_type == _HEX_DATA:
            _store_hex_data(buffers, upper_address, address, data, line_number)
        elif record_type == _HEX_EOF:
            _validate_hex_control_record(length, address, 0, "EOF", line_number)
            eof_seen = True
        elif record_type == _HEX_EXTENDED_LINEAR_ADDRESS:
            _validate_hex_control_record(
                length,
                address,
                _HEX_EXTENDED_ADDRESS_SIZE,
                "linear address",
                line_number,
            )
            upper_address = int.from_bytes(data, "big") << 16
        elif record_type == _HEX_START_LINEAR_ADDRESS:
            _validate_hex_control_record(
                length,
                address,
                _HEX_START_ADDRESS_SIZE,
                "start address",
                line_number,
            )
        else:
            msg = f"ESC firmware Intel HEX uses unsupported record type {record_type}"
            raise EscFirmwareUpdateError(msg)

    if not eof_seen:
        msg = "ESC firmware Intel HEX is missing its EOF record"
        raise EscFirmwareUpdateError(msg)
    return bytes(image)


def _validate_embedded_release_version(image: bytes, path: Path) -> None:
    metadata_start = image.find(_RELEASE_MAGIC)
    if metadata_start < 0:
        msg = "ESC firmware image does not contain Manafish release metadata"
        raise EscFirmwareUpdateError(msg)
    version_start = metadata_start + len(_RELEASE_MAGIC)
    version_end = image.find(b"\0", version_start, version_start + 32)
    if version_end < 0:
        msg = "ESC firmware image has invalid Manafish release metadata"
        raise EscFirmwareUpdateError(msg)
    try:
        embedded_version = image[version_start:version_end].decode("ascii")
    except UnicodeDecodeError as error:
        msg = "ESC firmware image has non-ASCII release metadata"
        raise EscFirmwareUpdateError(msg) from error
    if not is_valid_esc_firmware_version(embedded_version):
        msg = "ESC firmware image has an invalid embedded release version"
        raise EscFirmwareUpdateError(msg)
    name_match = re.fullmatch(r"esc-v(.+)\.(?:bin|hex)", path.name)
    if name_match is None or name_match.group(1) != embedded_version:
        msg = (
            f"ESC firmware filename version does not match embedded {embedded_version}"
        )
        raise EscFirmwareUpdateError(msg)


def load_esc_firmware_image(path: Path) -> bytes:
    """Load and strictly validate the Manafish F421 application image."""
    try:
        image = _parse_intel_hex(path) if path.suffix == ".hex" else path.read_bytes()
    except OSError as error:
        msg = f"Could not read ESC firmware image: {error}"
        raise EscFirmwareUpdateError(msg) from error

    if len(image) != ESC_FIRMWARE_IMAGE_SIZE:
        msg = f"ESC firmware image is {len(image)} bytes; expected {ESC_FIRMWARE_IMAGE_SIZE}"
        raise EscFirmwareUpdateError(msg)
    stack_pointer, reset_handler = struct.unpack_from("<II", image)
    if not _SRAM_START <= stack_pointer <= _SRAM_END:
        msg = "ESC firmware image has an invalid initial stack pointer"
        raise EscFirmwareUpdateError(msg)
    if (
        not ESC_FIRMWARE_APPLICATION_ADDRESS
        <= reset_handler
        < ESC_FIRMWARE_EEPROM_ADDRESS
        or reset_handler & 1 == 0
    ):
        msg = "ESC firmware image has an invalid reset handler"
        raise EscFirmwareUpdateError(msg)
    if not image[-32:].startswith(_TARGET_NAME):
        msg = "ESC firmware image is not for SKYSTARS_AM60_V2_F421"
        raise EscFirmwareUpdateError(msg)
    _validate_embedded_release_version(image, path)
    return image


def _checksum(data: bytes | bytearray) -> int:
    checksum = 0
    for value in data:
        checksum ^= value
    return checksum


def _control_packet(command: _Command, image: bytes | None = None) -> bytes:
    if command == _Command.BEGIN:
        if image is None:
            msg = "BEGIN requires an ESC firmware image"
            raise ValueError(msg)
        packet = bytearray(
            struct.pack(
                "<BBHIB2x",
                ESC_FIRMWARE_USB_CONTROL_START_BYTE,
                command,
                len(image),
                zlib.crc32(image),
                ESC_FIRMWARE_TARGET_F421_PB4_32K,
            )
        )
    else:
        packet = bytearray(ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE - 1)
        packet[0] = ESC_FIRMWARE_USB_CONTROL_START_BYTE
        packet[1] = command
    if len(packet) != ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE - 1:
        msg = "ESC firmware control packet layout does not match its configured size"
        raise EscFirmwareUpdateError(msg)
    packet.append(_checksum(packet))
    return bytes(packet)


def _data_packet(image: bytes, offset: int) -> tuple[bytes, int]:
    chunk = image[offset : offset + ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE]
    packet = bytearray(
        struct.pack("<BHB", ESC_FIRMWARE_USB_DATA_START_BYTE, offset, len(chunk))
    )
    packet.extend(chunk.ljust(ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE, b"\0"))
    packet.append(_checksum(packet))
    return bytes(packet), offset + len(chunk)


async def _write_packet(writer: asyncio.StreamWriter, packet: bytes) -> None:
    writer.write(packet)
    await writer.drain()


async def _read_status(
    reader: asyncio.StreamReader, read_buffer: bytearray
) -> tuple[_Status, int, int, int]:
    deadline = time.monotonic() + _STATUS_TIMEOUT_S
    while True:
        start = read_buffer.find(bytes((ESC_FIRMWARE_USB_STATUS_START_BYTE,)))
        if (
            start >= 0
            and len(read_buffer) >= start + ESC_FIRMWARE_USB_STATUS_PACKET_SIZE
        ):
            packet = read_buffer[start : start + ESC_FIRMWARE_USB_STATUS_PACKET_SIZE]
            if _checksum(packet[:-1]) != packet[-1]:
                del read_buffer[: start + 1]
                continue
            try:
                status = _Status(packet[1])
            except ValueError:
                del read_buffer[: start + 1]
                continue
            del read_buffer[: start + ESC_FIRMWARE_USB_STATUS_PACKET_SIZE]
            value = struct.unpack_from("<I", packet, 4)[0]
            return status, packet[2], packet[3], value
        if start > 0:
            del read_buffer[:start]
        elif start < 0 and len(read_buffer) > ESC_FIRMWARE_USB_STATUS_PACKET_SIZE:
            del read_buffer[:-ESC_FIRMWARE_USB_STATUS_PACKET_SIZE]

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            msg = "Timed out waiting for the Pico ESC firmware updater"
            raise EscFirmwareUpdateError(msg)
        data = await asyncio.wait_for(reader.read(128), timeout=remaining)
        if not data:
            msg = "MCU serial stream closed during ESC firmware update"
            raise EscFirmwareUpdateError(msg)
        read_buffer.extend(data)


async def _expect_status(
    reader: asyncio.StreamReader,
    read_buffer: bytearray,
    expected: _Status,
    expected_value: int | None = None,
) -> tuple[int, int]:
    status, motor, error, value = await _read_status(reader, read_buffer)
    if status == _Status.FAILED:
        raise EscFirmwareUpdateError(_format_updater_failure(motor, error))
    if status != expected or (expected_value is not None and value != expected_value):
        msg = f"Unexpected Pico ESC firmware status {status.name} (value {value})"
        raise EscFirmwareUpdateError(msg)
    return motor, value


async def _upload_image(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    image: bytes,
    read_buffer: bytearray,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    await _write_packet(writer, _control_packet(_Command.BEGIN, image))
    await _expect_status(reader, read_buffer, _Status.READY, len(image))

    for offset in range(0, len(image), ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE):
        packet, received = _data_packet(image, offset)
        await _write_packet(writer, packet)
        await _expect_status(reader, read_buffer, _Status.RECEIVED, received)
        if progress is not None:
            progress(max(1, received * 10 // len(image)), None)

    await _write_packet(writer, _control_packet(_Command.COMMIT))


async def _flash_all_escs(
    reader: asyncio.StreamReader,
    read_buffer: bytearray,
    image_size: int,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    while True:
        status_packet = await _read_status(reader, read_buffer)
        if _handle_flash_status(status_packet, image_size, progress):
            return


def _handle_flash_status(
    status_packet: tuple[_Status, int, int, int],
    image_size: int,
    progress: Callable[[int, int | None], None] | None,
) -> bool:
    status, motor, error, value = status_packet
    if status == _Status.FAILED:
        raise EscFirmwareUpdateError(_format_updater_failure(motor, error))
    if status == _Status.ENTERING_BOOTLOADER and progress is not None:
        progress(10, None)
    elif status == _Status.MOTOR_BEGIN:
        if value == 0:
            log_info(f"Flashing ESC firmware on ESC {motor + 1}/8...")
        if progress is not None:
            completed = motor * image_size + value
            progress(10 + completed * 90 // (NUM_MOTORS * image_size), motor)
    elif status == _Status.MOTOR_DONE:
        log_info(f"Verified ESC firmware on ESC {motor + 1}/8.")
        if progress is not None:
            completed = (motor + 1) * image_size
            progress(10 + completed * 90 // (NUM_MOTORS * image_size), motor)
    elif status == _Status.COMPLETE:
        if progress is not None:
            progress(100, NUM_MOTORS - 1)
        return True
    return False


async def _run_update(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    image: bytes,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    read_buffer = bytearray()
    await _upload_image(reader, writer, image, read_buffer, progress)
    await _flash_all_escs(reader, read_buffer, len(image), progress)


def _resolve_validated_image() -> tuple[Path, str, bytes] | None:
    resolved = resolve_esc_firmware()
    if resolved is None:
        log_error("ESC firmware update failed: no bundled firmware image found.")
        return None
    path, version = resolved
    try:
        return path, version, load_esc_firmware_image(path)
    except EscFirmwareUpdateError as error:
        log_error(f"ESC firmware update failed: {error}")
        return None


def _start_update(state: RovState, automatic: bool) -> None:
    update = state.esc_firmware_update
    update.active = True
    update.origin = (
        EscFirmwareUpdateOrigin.AUTOMATIC
        if automatic
        else EscFirmwareUpdateOrigin.MANUAL
    )
    update.stage = EscFirmwareUpdateStage.PREFLIGHT
    update.progress = 0
    update.current_esc = None
    update.target_version = None
    update.error = None


async def _preflight_update(
    state: RovState, serial_manager: SerialManager
) -> tuple[Path, str, bytes]:
    if state.rov_config.thruster_protocol != ThrusterProtocol.DSHOT:
        msg = "DShot must be selected before flashing ESC firmware."
        raise EscFirmwareUpdateError(msg)
    resolved = _resolve_validated_image()
    if resolved is None:
        msg = "No valid bundled ESC firmware image was found."
        raise EscFirmwareUpdateError(msg)
    if not await serial_manager.ensure_connection():
        msg = "The thruster MCU is not connected."
        raise EscFirmwareUpdateError(msg)
    if not _thrusters_idle(state):
        msg = "The thrusters are active."
        raise EscFirmwareUpdateError(msg)
    return resolved


async def _perform_update(
    state: RovState,
    serial_manager: SerialManager,
    release: tuple[Path, str, bytes],
    *,
    show_toasts: bool,
) -> None:
    path, version, image = release
    state.mcu_flashing = True
    progress = _EscFlashProgress(state, show_toasts)
    progress(0, None)
    # Normal thruster writes stop while mcu_flashing is set. Give the Pico's
    # 200 ms command watchdog time to force every channel to neutral before
    # asking it to enter the ESC bootloaders.
    await asyncio.sleep(_DISARM_SETTLE_S)
    async with serial_manager.io_lock:
        reader = serial_manager.get_reader()
        writer = serial_manager.get_writer()
        log_info(f"Flashing all ESCs with ESC firmware {version} from {path}")
        await _run_update(reader, writer, image, progress)


def _finish_successful_update(
    state: RovState, version: str, *, show_toasts: bool
) -> None:
    log_info(f"ESC firmware {version} flashed and verified on all eight ESCs.")
    # Programming verification proves the bytes written correctly, but
    # installed identity remains live telemetry. Clear stale reports and let
    # the restarted ESCs repopulate them over DShot.
    state.device_info.esc_firmware_versions = [None] * NUM_MOTORS
    update = state.esc_firmware_update
    update.stage = EscFirmwareUpdateStage.AWAITING_TELEMETRY
    update.progress = 100
    update.current_esc = None
    update.active = False
    _notify_esc_flash_success(show_toasts)


async def _abort_update(serial_manager: SerialManager) -> None:
    with contextlib.suppress(OSError, RuntimeError):
        await _write_packet(
            serial_manager.get_writer(), _control_packet(_Command.ABORT)
        )


async def flash_esc_firmware(
    state: RovState,
    serial_manager: SerialManager,
    *,
    show_toasts: bool = True,
    automatic: bool = False,
) -> bool:
    """Validate and flash the bundled ESC firmware image to all eight ESCs."""
    if state.mcu_flash_lock.locked():
        update = state.esc_firmware_update
        if update.active:
            log_info("ESC firmware update is already running.")
            if show_toasts:
                motor = None if update.current_esc is None else update.current_esc - 1
                _toast_esc_flash_progress(update.progress, motor)
        else:
            message = "Another firmware update is already running."
            log_warn(message)
            _notify_esc_flash_error(show_toasts, message)
        return False

    async with state.mcu_flash_lock:
        update = state.esc_firmware_update
        _start_update(state, automatic)
        try:
            release = await _preflight_update(state, serial_manager)
            _, version, _ = release
            update.target_version = version
            await _perform_update(
                state,
                serial_manager,
                release,
                show_toasts=show_toasts,
            )
            _finish_successful_update(state, version, show_toasts=show_toasts)
            return True
        except asyncio.CancelledError:
            update.active = False
            update.stage = EscFirmwareUpdateStage.FAILED
            update.error = "ESC firmware update was cancelled."
            await _abort_update(serial_manager)
            raise
        except (EscFirmwareUpdateError, TimeoutError, OSError, RuntimeError) as error:
            log_error(f"ESC firmware update failed: {error}")
            update.active = False
            update.stage = EscFirmwareUpdateStage.FAILED
            update.error = str(error)
            _notify_esc_flash_error(show_toasts, str(error))
            await _abort_update(serial_manager)
            return False
        finally:
            state.mcu_flashing = False
            update.active = False
            if update.stage in (
                EscFirmwareUpdateStage.PREFLIGHT,
                EscFirmwareUpdateStage.UPLOADING,
                EscFirmwareUpdateStage.PROGRAMMING,
            ):
                update.stage = EscFirmwareUpdateStage.FAILED
                update.error = (
                    update.error or "ESC firmware update stopped unexpectedly."
                )
