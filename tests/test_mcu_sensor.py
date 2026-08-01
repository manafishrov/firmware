import asyncio

from rov_firmware.constants import MCU_PROTOCOL_DSHOT, MCU_VERSION_START_BYTE
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
