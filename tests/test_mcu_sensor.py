from pathlib import Path

from rov_firmware.constants import (
    MCU_AUTO_UPDATE_WINDOW_S,
    MCU_PROTOCOL_DSHOT,
    MCU_TELEMETRY_TYPE_CURRENT,
    MCU_TELEMETRY_TYPE_ESC_VERSION_CHUNK,
    MCU_TELEMETRY_TYPE_ESC_VERSION_COMPLETE,
    MCU_TELEMETRY_TYPE_ESC_VERSION_LENGTH,
    MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
    MCU_VERSION_START_BYTE,
)
from rov_firmware.models.config import ThrusterProtocol
from rov_firmware.sensors import mcu as mcu_module
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.serial import SerialManager


def _version_packet(protocol: int, dshot_speed: int) -> bytes:
    packet = bytearray(
        [
            MCU_VERSION_START_BYTE,
            1,
            2,
            3,
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


def test_version_packet_acknowledges_mcu_without_reverting_requested_config(
    rov_state, monkeypatch
):
    rov_state.rov_config.thruster_protocol = ThrusterProtocol.PWM
    rov_state.rov_config.dshot_speed = 300
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    monkeypatch.setattr(sensor, "_get_expected_version", lambda: "1.2.3")

    sensor._handle_version_packet(_version_packet(MCU_PROTOCOL_DSHOT, 600))

    assert serial_manager.mcu_protocol_config == ("dshot", 600)
    assert rov_state.rov_config.thruster_protocol == ThrusterProtocol.PWM
    assert rov_state.rov_config.dshot_speed == 300
    assert rov_state.device_info.mcu_firmware_version == "1.2.3"


def test_version_packet_does_not_reflash_matching_prerelease_bundle(
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

    sensor._handle_version_packet(_version_packet(MCU_PROTOCOL_DSHOT, 600))

    assert rov_state.device_info.mcu_firmware_version == "1.2.3"


def test_signal_quality_updates_do_not_keep_stale_current_alive(rov_state, monkeypatch):
    now = 10.0
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: now)
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    sensor._update_telemetry_item(0, MCU_TELEMETRY_TYPE_CURRENT, 42)

    now = 14.0
    sensor._update_telemetry_item(0, MCU_TELEMETRY_TYPE_SIGNAL_QUALITY, 10_000)
    sensor._expire_stale_telemetry()

    assert rov_state.mcu_telemetry.current[0] == 0
    assert rov_state.mcu_telemetry.signal_quality[0] == 100


def test_esc_firmware_version_is_assembled_from_live_telemetry(rov_state, monkeypatch):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    version = b"2.20.1-rc.3"
    reported_versions: list[str | None] = [version.decode()] * 8
    rov_state.device_info.esc_firmware_versions = reported_versions
    rov_state.device_info.esc_firmware_versions[3] = None
    monkeypatch.setattr(
        mcu_module,
        "resolve_esc_firmware",
        lambda: (Path("esc-v2.20.2.bin"), "2.20.2"),
    )

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


def test_version_packet_stops_scheduling_esc_reconciliation_after_startup_window(
    rov_state, monkeypatch
):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    sensor._startup_time = 0.0
    scheduled = []
    monkeypatch.setattr(
        mcu_module.time, "monotonic", lambda: MCU_AUTO_UPDATE_WINDOW_S + 1
    )
    monkeypatch.setattr(sensor, "_get_expected_version", lambda: "1.2.3")
    monkeypatch.setattr(mcu_module, "mcu_update_required", lambda *_args: False)
    monkeypatch.setattr(
        sensor, "_schedule_esc_firmware_reconciliation", lambda: scheduled.append(True)
    )

    sensor._handle_version_packet(_version_packet(MCU_PROTOCOL_DSHOT, 600))

    assert scheduled == []
