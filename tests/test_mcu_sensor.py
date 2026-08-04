import asyncio

from rov_firmware.constants import (
    MCU_PROTOCOL_DSHOT,
    MCU_TELEMETRY_TYPE_CURRENT,
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
    queue = asyncio.Queue()
    monkeypatch.setattr(mcu_module, "get_message_queue", lambda: queue)
    rov_state.rov_config.thruster_protocol = ThrusterProtocol.PWM
    rov_state.rov_config.dshot_speed = 300
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    monkeypatch.setattr(sensor, "_get_expected_version", lambda: "1.2.3")

    sensor._handle_version_packet(_version_packet(MCU_PROTOCOL_DSHOT, 600))

    assert serial_manager.mcu_protocol_config == ("dshot", 600)
    assert rov_state.rov_config.thruster_protocol == ThrusterProtocol.PWM
    assert rov_state.rov_config.dshot_speed == 300
    assert queue.get_nowait().payload.thruster_protocol == ThrusterProtocol.PWM


def test_version_packet_does_not_reflash_matching_prerelease_bundle(
    rov_state, monkeypatch
):
    queue = asyncio.Queue()
    monkeypatch.setattr(mcu_module, "get_message_queue", lambda: queue)
    serial_manager = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial_manager)
    monkeypatch.setattr(sensor, "_get_expected_version", lambda: "1.2.3-rc.1")
    monkeypatch.setattr(mcu_module, "mcu_update_required", lambda *_args: False)

    def unexpected_flash() -> None:
        msg = "unexpected flash"
        raise AssertionError(msg)

    monkeypatch.setattr(sensor, "_flash_mcu", unexpected_flash)

    sensor._handle_version_packet(_version_packet(MCU_PROTOCOL_DSHOT, 600))

    assert rov_state.rov_config.mcu_firmware_version == "1.2.3"


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
