import asyncio
from pathlib import Path
import struct
from typing import cast

import pytest

from rov_firmware import esc_firmware
from rov_firmware.constants import (
    ESC_FIRMWARE_APPLICATION_ADDRESS,
    ESC_FIRMWARE_EEPROM_ADDRESS,
    ESC_FIRMWARE_IMAGE_SIZE,
    ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE,
    ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE,
    ESC_FIRMWARE_USB_STATUS_PACKET_SIZE,
)
from rov_firmware.serial import SerialManager


def _valid_image() -> bytes:
    image = bytearray([0xFF]) * ESC_FIRMWARE_IMAGE_SIZE
    struct.pack_into(
        "<II", image, 0, 0x20001000, ESC_FIRMWARE_APPLICATION_ADDRESS + 0x101
    )
    image[-32 : -32 + len(esc_firmware._TARGET_NAME)] = esc_firmware._TARGET_NAME
    metadata = esc_firmware._RELEASE_MAGIC + b"2.20.0\0"
    image[64 : 64 + len(metadata)] = metadata
    return bytes(image)


def _hex_record(record_type: int, address: int, data: bytes) -> str:
    record = bytearray((len(data), address >> 8, address & 0xFF, record_type))
    record.extend(data)
    record.append((-sum(record)) & 0xFF)
    return f":{record.hex().upper()}"


def _status_packet(status: esc_firmware._Status, value: int = 0) -> bytes:
    packet = bytearray(ESC_FIRMWARE_USB_STATUS_PACKET_SIZE)
    packet[0] = esc_firmware.ESC_FIRMWARE_USB_STATUS_START_BYTE
    packet[1] = status
    struct.pack_into("<I", packet, 4, value)
    packet[-1] = esc_firmware._checksum(packet[:-1])
    return bytes(packet)


def test_load_esc_firmware_image_accepts_exact_target_binary(tmp_path):
    path = tmp_path / "esc-v2.20.0.bin"
    expected = _valid_image()
    path.write_bytes(expected)

    assert esc_firmware.load_esc_firmware_image(path) == expected


def test_load_esc_firmware_image_rejects_renamed_release(tmp_path):
    path = tmp_path / "esc-v2.20.1.bin"
    path.write_bytes(_valid_image())

    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError, match=r"does not match embedded 2\.20\.0"
    ):
        esc_firmware.load_esc_firmware_image(path)


def test_load_esc_firmware_image_normalizes_sparse_intel_hex(tmp_path):
    expected = _valid_image()
    path = tmp_path / "esc-v2.20.0.hex"
    path.write_text(
        "\n".join(
            (
                _hex_record(4, 0, b"\x08\x00"),
                _hex_record(0, 0x1000, expected[:8]),
                _hex_record(0, 0x1040, expected[64:96]),
                _hex_record(0, 0x7BE0, expected[-32:]),
                _hex_record(1, 0, b""),
            )
        ),
        encoding="ascii",
    )

    assert esc_firmware.load_esc_firmware_image(path) == expected


def test_load_esc_firmware_image_rejects_bootloader_write(tmp_path):
    path = tmp_path / "esc-v2.20.0.hex"
    path.write_text(
        "\n".join(
            (
                _hex_record(4, 0, b"\x08\x00"),
                _hex_record(0, 0, b"unsafe"),
                _hex_record(1, 0, b""),
            )
        ),
        encoding="ascii",
    )

    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError, match="outside the application"
    ):
        esc_firmware.load_esc_firmware_image(path)


def test_load_esc_firmware_image_rejects_reset_handler_in_eeprom(tmp_path):
    path = tmp_path / "esc-v2.20.0.bin"
    image = bytearray(_valid_image())
    struct.pack_into("<I", image, 4, ESC_FIRMWARE_EEPROM_ADDRESS + 1)
    path.write_bytes(image)

    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError, match="invalid reset handler"
    ):
        esc_firmware.load_esc_firmware_image(path)


def test_load_esc_firmware_image_rejects_non_thumb_reset_handler(tmp_path):
    path = tmp_path / "esc-v2.20.0.bin"
    image = bytearray(_valid_image())
    struct.pack_into("<I", image, 4, ESC_FIRMWARE_APPLICATION_ADDRESS + 0x100)
    path.write_bytes(image)

    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError, match="invalid reset handler"
    ):
        esc_firmware.load_esc_firmware_image(path)


def test_resolve_esc_firmware_prefers_latest_version_and_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    firmware_dir = tmp_path / "esc-firmware"
    firmware_dir.mkdir()
    (firmware_dir / "esc-v2.19.0.bin").touch()
    (firmware_dir / "esc-v2.20.0-rc.2.hex").touch()
    preferred = firmware_dir / "esc-v2.20.0-rc.2.bin"
    preferred.touch()

    assert esc_firmware.resolve_esc_firmware() == (preferred, "2.20.0-rc.2")


@pytest.mark.parametrize(
    ("version", "valid"),
    [
        ("2.20.0", True),
        ("2.20.0-rc.2+build.7", True),
        ("2.20.0-rc2", False),
        ("2.20.0-rc-2", False),
        ("2.20.0-RC.2", False),
        ("2.20.0-a..b", False),
        ("2.20.0-01", False),
        ("2.20.0+build..7", False),
    ],
)
def test_esc_firmware_version_requires_strict_semver(version, valid):
    assert esc_firmware.is_valid_esc_firmware_version(version) is valid


def test_usb_packets_have_fixed_sizes_and_checksums():
    image = _valid_image()
    begin = esc_firmware._control_packet(esc_firmware._Command.BEGIN, image)
    data, received = esc_firmware._data_packet(image, 0)

    assert len(begin) == ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE
    assert esc_firmware._checksum(begin[:-1]) == begin[-1]
    assert len(data) == 1 + 2 + 1 + ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE + 1
    assert esc_firmware._checksum(data[:-1]) == data[-1]
    assert received == ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE


def test_begin_packet_rejects_mismatched_configured_size(monkeypatch):
    monkeypatch.setattr(
        esc_firmware,
        "ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE",
        ESC_FIRMWARE_USB_CONTROL_PACKET_SIZE + 1,
    )

    with pytest.raises(esc_firmware.EscFirmwareUpdateError, match="configured size"):
        esc_firmware._control_packet(esc_firmware._Command.BEGIN, _valid_image())


def test_update_preserves_status_bytes_between_upload_and_flash():
    image = b"x"

    class RecordingWriter:
        def __init__(self):
            self.packets = []

        def write(self, packet):
            self.packets.append(packet)

        async def drain(self):
            return None

    async def run_update() -> list[bytes]:
        reader = asyncio.StreamReader()
        reader.feed_data(
            _status_packet(esc_firmware._Status.READY, len(image))
            + _status_packet(esc_firmware._Status.RECEIVED, len(image))
            + _status_packet(esc_firmware._Status.COMPLETE)
        )
        reader.feed_eof()
        recording_writer = RecordingWriter()
        writer = cast(asyncio.StreamWriter, recording_writer)
        await esc_firmware._run_update(reader, writer, image)
        return recording_writer.packets

    packets = asyncio.run(run_update())

    assert len(packets) == 3


def test_precommit_updater_failure_confirms_no_esc_was_modified():
    class RecordingWriter:
        def write(self, _packet):
            return None

        async def drain(self):
            return None

    async def run_update() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(_status_packet(esc_firmware._Status.FAILED))
        reader.feed_eof()
        await esc_firmware._run_update(
            reader,
            cast(asyncio.StreamWriter, RecordingWriter()),
            b"x",
        )

    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError,
        match=r"No ESC was modified\.$",
    ):
        asyncio.run(run_update())


def test_upload_retries_a_missing_chunk_acknowledgement(monkeypatch):
    attempts = 0

    class RecordingWriter:
        def __init__(self):
            self.packets = []

        def write(self, packet):
            self.packets.append(packet)

        async def drain(self):
            return None

    async def fake_expect_status(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            msg = "missing acknowledgement"
            raise esc_firmware._PicoStatusTimeoutError(msg)
        return 0xFF, ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE

    async def run_test() -> list[bytes]:
        writer = RecordingWriter()
        packet = bytes((esc_firmware.ESC_FIRMWARE_USB_DATA_START_BYTE,))
        monkeypatch.setattr(esc_firmware, "_expect_status", fake_expect_status)
        await esc_firmware._write_with_ack_retry(
            (
                asyncio.StreamReader(),
                cast(asyncio.StreamWriter, writer),
                bytearray(),
            ),
            packet,
            (
                esc_firmware._Status.RECEIVED,
                ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE,
            ),
            uploaded_bytes=0,
        )
        return writer.packets

    packets = asyncio.run(run_test())

    assert attempts == 2
    assert packets == [
        bytes((esc_firmware.ESC_FIRMWARE_USB_DATA_START_BYTE,)),
        bytes((esc_firmware.ESC_FIRMWARE_USB_DATA_START_BYTE,)),
    ]


def test_expected_status_ignores_stale_upload_acknowledgement():
    async def run_test() -> tuple[int, int]:
        reader = asyncio.StreamReader()
        reader.feed_data(
            _status_packet(
                esc_firmware._Status.RECEIVED,
                ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE,
            )
            + _status_packet(
                esc_firmware._Status.RECEIVED,
                ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE * 2,
            )
        )
        reader.feed_eof()
        return await esc_firmware._expect_status(
            reader,
            bytearray(),
            esc_firmware._Status.RECEIVED,
            ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE * 2,
        )

    assert asyncio.run(run_test()) == (
        0,
        ESC_FIRMWARE_USB_DATA_PAYLOAD_SIZE * 2,
    )


def test_expected_status_ignores_stale_abort_from_previous_attempt():
    async def run_test() -> tuple[int, int]:
        reader = asyncio.StreamReader()
        reader.feed_data(
            _status_packet(esc_firmware._Status.ABORTED)
            + _status_packet(esc_firmware._Status.READY, ESC_FIRMWARE_IMAGE_SIZE)
        )
        reader.feed_eof()
        return await esc_firmware._expect_status(
            reader,
            bytearray(),
            esc_firmware._Status.READY,
            ESC_FIRMWARE_IMAGE_SIZE,
        )

    assert asyncio.run(run_test()) == (0, ESC_FIRMWARE_IMAGE_SIZE)


def test_status_reader_resynchronizes_after_false_start_byte():
    status = bytearray(ESC_FIRMWARE_USB_STATUS_PACKET_SIZE)
    status[0] = esc_firmware.ESC_FIRMWARE_USB_STATUS_START_BYTE
    status[1] = esc_firmware._Status.READY
    struct.pack_into("<I", status, 4, ESC_FIRMWARE_IMAGE_SIZE)
    status[-1] = esc_firmware._checksum(status[:-1])
    read_buffer = bytearray((esc_firmware.ESC_FIRMWARE_USB_STATUS_START_BYTE,))
    read_buffer.extend(b"not-a-frame")
    read_buffer.extend(status)

    async def read_status():
        return await esc_firmware._read_status(asyncio.StreamReader(), read_buffer)

    result = asyncio.run(read_status())

    assert result == (esc_firmware._Status.READY, 0, 0, ESC_FIRMWARE_IMAGE_SIZE)


def test_flash_status_reports_monotonic_per_esc_progress():
    progress: list[tuple[int, int | None]] = []

    def callback(percent: int, motor: int | None) -> None:
        progress.append((percent, motor))

    assert not esc_firmware._handle_flash_status(
        (esc_firmware._Status.ENTERING_BOOTLOADER, 0xFF, 0, 0),
        ESC_FIRMWARE_IMAGE_SIZE,
        callback,
    )
    assert not esc_firmware._handle_flash_status(
        (esc_firmware._Status.MOTOR_BEGIN, 3, 0, ESC_FIRMWARE_IMAGE_SIZE // 2),
        ESC_FIRMWARE_IMAGE_SIZE,
        callback,
    )
    assert esc_firmware._handle_flash_status(
        (esc_firmware._Status.COMPLETE, 0xFF, 0, 0),
        ESC_FIRMWARE_IMAGE_SIZE,
        callback,
    )

    assert progress[0] == (10, None)
    assert progress[1][0] > progress[0][0]
    assert progress[1][1] == 3
    assert progress[2] == (100, 7)


def test_flash_status_reports_friendly_one_based_failure():
    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError,
        match=r"ESC 4 failed because flash verification failed",
    ):
        esc_firmware._handle_flash_status(
            (esc_firmware._Status.FAILED, 3, esc_firmware._Error.VERIFY, 0),
            ESC_FIRMWARE_IMAGE_SIZE,
            None,
        )


def test_preflight_requires_live_dshot_acknowledgement(rov_state):
    class UnacknowledgedSerialManager:
        mcu_protocol_config = None

        async def ensure_connection(self):
            return True

    rov_state.system_status.thruster_control_ready = True
    with pytest.raises(
        esc_firmware.EscFirmwareUpdateError,
        match="has not acknowledged the selected DShot configuration",
    ):
        asyncio.run(
            esc_firmware._preflight_update(
                rov_state,
                cast(SerialManager, UnacknowledgedSerialManager()),
            )
        )


def test_preflight_allows_recovery_retry_without_runtime_config_ack(
    rov_state, monkeypatch
):
    class RecoverySerialManager:
        mcu_protocol_config = None

        async def ensure_connection(self):
            return True

    image = _valid_image()
    rov_state.esc_firmware_recovery_required = True
    monkeypatch.setattr(
        esc_firmware,
        "_resolve_validated_image",
        lambda: (Path("esc-v2.20.0.bin"), "2.20.0", image),
    )

    release = asyncio.run(
        esc_firmware._preflight_update(
            rov_state,
            cast(SerialManager, RecoverySerialManager()),
        )
    )

    assert release == (Path("esc-v2.20.0.bin"), "2.20.0", image)


def test_concurrent_flash_request_is_rejected_and_success_updates_live_state(
    rov_state, monkeypatch
):
    image = _valid_image()
    connection_started = asyncio.Event()
    allow_connection = asyncio.Event()

    class FakeSerialManager:
        def __init__(self):
            self.io_lock = asyncio.Lock()
            self.write_lock = asyncio.Lock()
            self.mcu_protocol_config = ("dshot", rov_state.rov_config.dshot_speed)

        async def ensure_connection(self):
            connection_started.set()
            await allow_connection.wait()
            return True

        def get_reader(self):
            return object()

        def get_writer(self):
            return object()

    async def fake_run_update(
        _reader, _writer, firmware, _progress, *, on_commit_started
    ):
        assert firmware == image
        on_commit_started()

    async def run_test():
        manager = cast(SerialManager, FakeSerialManager())
        rov_state.system_status.thruster_control_ready = True
        monkeypatch.setattr(
            esc_firmware,
            "_resolve_validated_image",
            lambda: (Path("esc-v2.20.0.bin"), "2.20.0", image),
        )
        monkeypatch.setattr(esc_firmware, "_run_update", fake_run_update)
        monkeypatch.setattr(esc_firmware, "_DISARM_SETTLE_S", 0)

        first = asyncio.create_task(
            esc_firmware.flash_esc_firmware(rov_state, manager, show_toasts=False)
        )
        await connection_started.wait()
        assert not await esc_firmware.flash_esc_firmware(
            rov_state, manager, show_toasts=False
        )
        allow_connection.set()
        assert await first

    asyncio.run(run_test())
    assert rov_state.device_info.esc_firmware_versions == [None] * 8
    assert rov_state.esc_firmware_update.stage == "awaitingTelemetry"
    assert rov_state.esc_firmware_update.target_version == "2.20.0"
    assert not rov_state.esc_firmware_recovery_required


def test_cancelled_flash_aborts_updater_and_clears_state(rov_state, monkeypatch):
    image = _valid_image()

    class RecordingWriter:
        def __init__(self):
            self.packets = []

        def write(self, packet):
            self.packets.append(packet)

        async def drain(self):
            return None

    class FakeSerialManager:
        def __init__(self):
            self.io_lock = asyncio.Lock()
            self.write_lock = asyncio.Lock()
            self.mcu_protocol_config = ("dshot", rov_state.rov_config.dshot_speed)
            self.writer = RecordingWriter()

        async def ensure_connection(self):
            return True

        def get_reader(self):
            return object()

        def get_writer(self):
            return self.writer

    async def cancelled_update(_reader, _writer, _firmware, _progress, **_kwargs):
        raise asyncio.CancelledError

    manager = FakeSerialManager()
    rov_state.system_status.thruster_control_ready = True
    monkeypatch.setattr(
        esc_firmware,
        "_resolve_validated_image",
        lambda: (Path("esc-v2.20.0.bin"), "2.20.0", image),
    )
    monkeypatch.setattr(esc_firmware, "_run_update", cancelled_update)
    monkeypatch.setattr(esc_firmware, "_DISARM_SETTLE_S", 0)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            esc_firmware.flash_esc_firmware(
                rov_state,
                cast(SerialManager, manager),
                show_toasts=False,
            )
        )

    assert manager.writer.packets[-1][1] == esc_firmware._Command.ABORT
    assert not rov_state.mcu_flashing


def test_failure_after_commit_keeps_thrusters_blocked_for_recovery_retry(
    rov_state, monkeypatch
):
    image = _valid_image()

    class RecordingWriter:
        def write(self, _packet):
            return None

        async def drain(self):
            return None

    class FakeSerialManager:
        def __init__(self):
            self.io_lock = asyncio.Lock()
            self.write_lock = asyncio.Lock()
            self.mcu_protocol_config = ("dshot", rov_state.rov_config.dshot_speed)
            self.writer = RecordingWriter()

        async def ensure_connection(self):
            return True

        def get_reader(self):
            return object()

        def get_writer(self):
            return self.writer

    async def failed_update(
        _reader, _writer, _firmware, _progress, *, on_commit_started
    ):
        on_commit_started()
        msg = "ESC 1 failed"
        raise esc_firmware.EscFirmwareUpdateError(msg)

    manager = FakeSerialManager()
    rov_state.system_status.thruster_control_ready = True
    monkeypatch.setattr(
        esc_firmware,
        "_resolve_validated_image",
        lambda: (Path("esc-v2.20.0.bin"), "2.20.0", image),
    )
    monkeypatch.setattr(esc_firmware, "_run_update", failed_update)
    monkeypatch.setattr(esc_firmware, "_DISARM_SETTLE_S", 0)

    succeeded = asyncio.run(
        esc_firmware.flash_esc_firmware(
            rov_state,
            cast(SerialManager, manager),
            show_toasts=False,
        )
    )

    assert not succeeded
    assert rov_state.esc_firmware_recovery_required
    assert not rov_state.system_status.thruster_control_ready


def test_connection_loss_before_programming_sets_terminal_failure(
    rov_state, monkeypatch
):
    image = _valid_image()

    class DisconnectedSerialManager:
        def __init__(self):
            self.io_lock = asyncio.Lock()
            self.write_lock = asyncio.Lock()
            self.mcu_protocol_config = ("dshot", rov_state.rov_config.dshot_speed)

        async def ensure_connection(self):
            return True

        def get_reader(self):
            msg = "Serial not initialized"
            raise RuntimeError(msg)

        def get_writer(self):
            msg = "Serial not initialized"
            raise RuntimeError(msg)

    monkeypatch.setattr(
        esc_firmware,
        "_resolve_validated_image",
        lambda: (Path("esc-v2.20.0.bin"), "2.20.0", image),
    )
    monkeypatch.setattr(esc_firmware, "_DISARM_SETTLE_S", 0)
    rov_state.system_status.thruster_control_ready = True

    succeeded = asyncio.run(
        esc_firmware.flash_esc_firmware(
            rov_state,
            cast(SerialManager, DisconnectedSerialManager()),
            show_toasts=False,
        )
    )

    assert not succeeded
    assert rov_state.esc_firmware_update.stage == "failed"
    assert rov_state.esc_firmware_update.error == "Serial not initialized"
