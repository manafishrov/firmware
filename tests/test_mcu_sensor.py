import asyncio

from rov_firmware.constants import (
    MCU_PROTOCOL_DSHOT,
    MCU_RELEASE_VERSION_MAX_LENGTH,
    MCU_RELEASE_VERSION_START_BYTE,
    MCU_RUNTIME_CONFIG_STATUS_START_BYTE,
    MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE,
    MCU_TELEMETRY_TYPE_CURRENT,
    MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK,
    MCU_TELEMETRY_TYPE_ESC_VERSION_COMPLETE,
    MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH,
    MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
)
from rov_firmware.models.config import ThrusterProtocol
from rov_firmware.sensors import mcu as mcu_module
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.serial import SerialManager


class _CompletedTask:
    def done(self) -> bool:
        return True


class _RecordingLoop:
    def __init__(self) -> None:
        self.created = 0

    def create_task(self, coroutine) -> _CompletedTask:
        self.created += 1
        coroutine.close()
        return _CompletedTask()


def _runtime_config_status_packet(protocol: int, dshot_speed: int) -> bytes:
    packet = bytearray(
        [
            MCU_RUNTIME_CONFIG_STATUS_START_BYTE,
            protocol,
            dshot_speed & 0xFF,
            dshot_speed >> 8,
        ]
    )
    checksum = 0
    for value in packet:
        checksum ^= value
    packet.append(checksum)
    return bytes(packet)


def _release_version_packet(version: str) -> bytes:
    encoded = version.encode("ascii")
    packet = bytearray([MCU_RELEASE_VERSION_START_BYTE, len(encoded), *encoded])
    checksum = 0
    for value in packet:
        checksum ^= value
    packet.append(checksum)
    return bytes(packet)


def test_runtime_config_status_acknowledges_mcu_without_changing_release_identity(
    rov_state,
):
    rov_state.rov_config.thruster_protocol = ThrusterProtocol.PWM
    rov_state.rov_config.dshot_speed = 300
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)

    # Fixed MCU protocol vector for DShot600. Keep this independent of the
    # helper so a matching encoder/decoder defect cannot pass the contract test.
    sensor._handle_runtime_config_status_packet(bytes((0xD5, 0x01, 0x58, 0x02, 0x8E)))

    assert serial_manager.mcu_protocol_config == ("dshot", 600)
    assert rov_state.rov_config.thruster_protocol == ThrusterProtocol.PWM
    assert rov_state.rov_config.dshot_speed == 300
    assert rov_state.device_info.mcu_firmware_version == ""


def test_runtime_config_status_rejects_unknown_protocol(rov_state):
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)

    packet = _runtime_config_status_packet(0x7F, 600)

    assert not sensor._validate_runtime_config_status_packet(packet)
    assert serial_manager.mcu_protocol_config is None


def test_runtime_config_status_does_not_reflash_matching_prerelease_bundle(
    rov_state, monkeypatch
):
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    monkeypatch.setattr(sensor, "_get_expected_version", lambda: "1.2.3-rc.1")
    monkeypatch.setattr(mcu_module, "mcu_update_required", lambda *_args: False)

    def unexpected_flash() -> None:
        msg = "unexpected flash"
        raise AssertionError(msg)

    monkeypatch.setattr(sensor, "_flash_mcu", unexpected_flash)

    sensor._handle_release_version_packet(_release_version_packet("1.2.3-rc.1"))
    sensor._handle_runtime_config_status_packet(
        _runtime_config_status_packet(MCU_PROTOCOL_DSHOT, 600)
    )

    assert rov_state.device_info.mcu_firmware_version == "1.2.3-rc.1"


def test_release_version_packet_rejects_legacy_rc_spelling(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))

    sensor._handle_release_version_packet(_release_version_packet("1.2.3-rc1"))

    assert rov_state.device_info.mcu_firmware_version == ""


def test_release_version_packet_rejects_uppercase_rc_spelling(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))

    sensor._handle_release_version_packet(_release_version_packet("1.2.3-RC.1"))

    assert rov_state.device_info.mcu_firmware_version == ""


def test_release_version_packet_parses_through_split_read_buffer(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    packet = _release_version_packet("1.2.3-rc.1")
    read_buffer = bytearray()

    sensor._consume_read_buffer(read_buffer, packet[:3])
    assert rov_state.device_info.mcu_firmware_version == ""

    sensor._consume_read_buffer(read_buffer, packet[3:])
    assert rov_state.device_info.mcu_firmware_version == "1.2.3-rc.1"


def test_release_identity_and_runtime_config_status_parse_in_wire_order(rov_state):
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    packets = _release_version_packet("1.2.3-rc.1") + bytes(
        (0xD5, 0x01, 0x58, 0x02, 0x8E)
    )

    sensor._consume_read_buffer(bytearray(), packets)

    assert rov_state.device_info.mcu_firmware_version == "1.2.3-rc.1"
    assert serial_manager.mcu_protocol_config == ("dshot", 600)


def test_release_version_buffer_ignores_bad_checksum_and_resynchronizes(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    damaged = bytearray(_release_version_packet("1.2.2"))
    damaged[-1] ^= 0xFF

    sensor._consume_read_buffer(
        bytearray(), bytes(damaged) + _release_version_packet("1.2.3")
    )

    assert rov_state.device_info.mcu_firmware_version == "1.2.3"


def test_release_version_buffer_rejects_oversized_length_and_resynchronizes(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    oversized_header = bytes(
        (MCU_RELEASE_VERSION_START_BYTE, MCU_RELEASE_VERSION_MAX_LENGTH + 1)
    )

    sensor._consume_read_buffer(
        bytearray(), oversized_header + _release_version_packet("1.2.3")
    )

    assert rov_state.device_info.mcu_firmware_version == "1.2.3"


def test_invalid_release_warning_is_once_per_connection_generation(
    rov_state, monkeypatch
):
    warnings: list[str] = []
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    monkeypatch.setattr(mcu_module, "log_warn", warnings.append)
    packet = _release_version_packet("1.2.3-rc1")

    sensor._handle_release_version_packet(packet)
    sensor._handle_release_version_packet(packet)
    serial_manager._connection_generation += 1
    sensor._handle_release_version_packet(packet)

    assert len(warnings) == 2


def test_clearing_serial_connection_clears_live_mcu_identity(rov_state):
    serial_manager = SerialManager(rov_state)
    rov_state.device_info.mcu_firmware_version = "1.2.3-rc.1"
    rov_state.system_status.thruster_control_ready = True

    asyncio.run(serial_manager._clear_connection_unlocked())

    assert rov_state.device_info.mcu_firmware_version == ""
    assert rov_state.system_status.thruster_control_ready is False


def test_matching_runtime_config_ack_marks_thruster_control_ready(rov_state):
    serial_manager = SerialManager(rov_state)

    serial_manager.record_mcu_protocol_config("dshot", 300)

    assert rov_state.system_status.thruster_control_ready is True


def test_version_mismatch_auto_flashes_only_once_per_service_start(
    rov_state, monkeypatch
):
    loop = _RecordingLoop()
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    monkeypatch.setattr(mcu_module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(mcu_module, "mcu_update_required", lambda *_args: True)

    sensor._auto_update_mcu_if_needed("1.2.2", "1.2.3")
    sensor._auto_update_mcu_if_needed("1.2.2", "1.2.3")

    assert loop.created == 1
    assert sensor._mcu_auto_flash_attempted is True


def test_signal_quality_updates_do_not_keep_stale_current_alive(rov_state, monkeypatch):
    now = 10.0
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: now)
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    sensor._update_telemetry_item(0, MCU_TELEMETRY_TYPE_CURRENT, 42)

    now = 14.0
    sensor._update_telemetry_item(0, MCU_TELEMETRY_TYPE_SIGNAL_QUALITY, 10_000)
    sensor._expire_stale_telemetry()

    assert rov_state.mcu_telemetry.current[0] == 0
    assert rov_state.mcu_telemetry.current_valid[0] is False
    assert rov_state.mcu_telemetry.signal_quality[0] == 100
    assert rov_state.mcu_telemetry.signal_quality_valid[0] is True


def test_stale_signal_quality_becomes_unavailable(rov_state, monkeypatch):
    now = 10.0
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: now)
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    sensor._update_telemetry_item(0, MCU_TELEMETRY_TYPE_SIGNAL_QUALITY, 0)

    assert rov_state.mcu_telemetry.signal_quality[0] == 0
    assert rov_state.mcu_telemetry.signal_quality_valid[0] is True

    now = 14.0
    sensor._expire_stale_telemetry()

    assert rov_state.mcu_telemetry.signal_quality[0] == 0
    assert rov_state.mcu_telemetry.signal_quality_valid[0] is False


def test_signal_quality_sentinel_is_reported_as_unavailable(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))

    sensor._update_telemetry_item(
        0,
        MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
        MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE,
    )

    assert rov_state.mcu_telemetry.signal_quality[0] == 0.0
    assert rov_state.mcu_telemetry.signal_quality_valid[0] is False


def test_current_telemetry_preserves_raw_edt_amperes(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))

    sensor._update_telemetry_item(2, MCU_TELEMETRY_TYPE_CURRENT, 3)

    assert rov_state.mcu_telemetry.current[2] == 3
    assert rov_state.mcu_telemetry.current_valid[2] is True


def test_current_telemetry_rejects_negative_usb_values(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))

    sensor._update_telemetry_item(2, MCU_TELEMETRY_TYPE_CURRENT, -1)

    assert rov_state.mcu_telemetry.current[2] == 0
    assert rov_state.mcu_telemetry.current_valid[2] is True


def test_esc_firmware_version_is_assembled_from_live_telemetry(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    version = b"2.20.1-rc.3"
    reported_versions: list[str | None] = [version.decode()] * 8
    rov_state.device_info.esc_firmware_versions = reported_versions
    rov_state.device_info.esc_firmware_versions[3] = None

    def report_version(motor: int, checksum: int) -> None:
        sensor._update_telemetry_item(
            motor, MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH, len(version)
        )
        for chunk_index, offset in enumerate(range(0, len(version), 3)):
            chunk = version[offset : offset + 3].ljust(3, b"\0")
            packed = int.from_bytes(chunk, "little") | (chunk_index << 24)
            sensor._update_telemetry_item(
                motor, MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK, packed
            )
        sensor._update_telemetry_item(
            motor, MCU_TELEMETRY_TYPE_ESC_VERSION_COMPLETE, checksum
        )

    # Fixed AM32 protocol vector for b"2.20.1-rc.3"; do not derive this with
    # the production CRC helper or a matching defect could pass the test.
    report_version(3, 0x03)
    rov_state.device_info.esc_firmware_versions[4] = None
    report_version(4, 0x02)

    assert rov_state.device_info.esc_firmware_versions[3] == "2.20.1-rc.3"
    assert rov_state.device_info.esc_firmware_versions[4] is None
