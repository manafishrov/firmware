import struct
import time

from rov_firmware.models.config import PartialRovConfig, RovConfig
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.serial import SerialManager


def packet(channel, kind, value):
    body = bytes((0xA5, channel, kind)) + struct.pack("<i", value)
    checksum = 0
    for value_byte in body:
        checksum ^= value_byte
    return body + bytes((checksum,))


def test_raw_and_board_packets_are_separate(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    buffer = bytearray()
    for data in (
        packet(0, 3, 91),
        packet(0, 9, 5000),
        packet(4, 9, 5000),
        packet(0, 10, 91000),
    ):
        sensor._consume_read_buffer(buffer, data)
    assert rov_state.mcu_telemetry.current[0] == 91
    assert rov_state.mcu_telemetry.board_current_ma == [5000, 5000]
    assert rov_state.mcu_telemetry.board_baseline_ma == [91000, None]
    snapshot = sensor.diagnostic_snapshot(time.monotonic())
    assert snapshot[0]["current"] == 91
    assert snapshot[0]["board_current_ma"] == 5000
    assert snapshot[0]["board_baseline_ma"] == 91000


def test_fragmented_batch_preserves_milliamp_reports(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    data = bytes((0xA6, 4)) + b"".join(
        packet(channel, kind, value)[1:-1]
        for channel, kind, value in (
            (0, 9, 5250),
            (4, 9, 5000),
            (0, 10, 91000),
            (4, 10, 87000),
        )
    )
    checksum = 0
    for value_byte in data:
        checksum ^= value_byte
    buffer = bytearray()
    for value_byte in data + bytes((checksum,)):
        sensor._consume_read_buffer(buffer, bytes((value_byte,)))
    assert not buffer
    assert rov_state.mcu_telemetry.board_current_ma == [5250, 5000]
    assert rov_state.mcu_telemetry.board_baseline_ma == [91000, 87000]


def test_invalid_board_ids_values_and_unavailable(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    for channel, kind, value in (
        (1, 9, 5000),
        (8, 9, 5000),
        (0, 9, -2),
        (0, 9, 255001),
    ):
        sensor._consume_read_buffer(bytearray(), packet(channel, kind, value))
    assert rov_state.mcu_telemetry.board_current_ma == [None, None]
    sensor._consume_read_buffer(bytearray(), packet(0, 9, 0))
    assert rov_state.mcu_telemetry.board_current_ma[0] == 0
    sensor._consume_read_buffer(bytearray(), packet(0, 9, -1))
    assert rov_state.mcu_telemetry.board_current_ma[0] is None


def test_lost_current_invalidation_cannot_survive_invalid_baseline(rov_state):
    sensor = McuSensor(rov_state, SerialManager(rov_state))
    sensor._consume_read_buffer(bytearray(), packet(0, 9, 5000))
    # The corresponding type-9 unavailable packet was lost in transport.
    sensor._consume_read_buffer(bytearray(), packet(0, 10, -1))
    assert rov_state.mcu_telemetry.board_current_ma[0] is None


def test_generation_and_reset_invalidate_calibrated_current(rov_state):
    serial = SerialManager(rov_state)
    sensor = McuSensor(rov_state, serial)
    sensor._consume_read_buffer(bytearray(), packet(0, 9, 5000))
    serial._connection_generation += 1
    sensor._consume_read_buffer(bytearray(), packet(0, 3, 91))
    assert rov_state.mcu_telemetry.board_current_ma == [None, None]
    sensor._consume_read_buffer(bytearray(), packet(4, 9, 5000))
    sensor._reset_telemetry()
    assert rov_state.mcu_telemetry.board_current_ma == [None, None]


def test_legacy_topology_setting_is_ignored_and_not_saved():
    config = RovConfig.model_validate({"currentSensingMode": "perMotor"})
    assert "currentSensingMode" not in config.model_dump(by_alias=True)
    partial = PartialRovConfig.model_validate({"currentSensingMode": "sharedBus"})
    assert partial.model_dump(exclude_unset=True) == {}
