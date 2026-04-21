import asyncio
import struct
from typing import Any, cast

import numpy as np
import pytest

from rov_firmware.constants import (
    MCU_CONFIG_START_BYTE,
    MCU_PROTOCOL_DSHOT,
    MCU_PROTOCOL_PWM,
    NUM_MOTORS,
    THRUSTER_FORWARD_PULSE_RANGE,
    THRUSTER_INPUT_START_BYTE,
    THRUSTER_NEUTRAL_PULSE_WIDTH,
    THRUSTER_REVERSE_PULSE_RANGE,
    THRUSTER_SEND_FREQUENCY,
)
from rov_firmware.models.config import ThrusterPinSetup
from rov_firmware.regulator import Regulator as RegulatorController
from rov_firmware.thrusters import Thrusters


class _WriterSpy:
    def __init__(self):
        self.writes = []
        self.drains = 0

    def write(self, data):
        self.writes.append(bytes(data))

    async def drain(self):
        self.drains += 1


@pytest.fixture
def thrusters(rov_state):
    return Thrusters(
        rov_state,
        cast(Any, object()),
        cast(Any, RegulatorController(rov_state)),
    )


def test_smooth_direction_vector_skips_smoothing_below_threshold(thrusters):
    thrusters.state.rov_config.smoothing_factor = 1 / THRUSTER_SEND_FREQUENCY

    direction_vector = np.array([1.0] * 8, dtype=np.float32)
    previous_direction_vector = np.zeros(8, dtype=np.float32)

    thrusters._smooth_direction_vector(direction_vector, previous_direction_vector)

    assert np.allclose(direction_vector, np.ones(8, dtype=np.float32))


def test_smooth_direction_vector_limits_step_size(thrusters):
    thrusters.state.rov_config.smoothing_factor = 0.5

    direction_vector = np.array(
        [1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.0, 0.0],
        dtype=np.float32,
    )
    previous_direction_vector = np.zeros(8, dtype=np.float32)

    thrusters._smooth_direction_vector(direction_vector, previous_direction_vector)

    step = 1 / (THRUSTER_SEND_FREQUENCY * 0.5)
    expected = np.array(
        [step, -step, step, -step, step, -step, 0.0, 0.0],
        dtype=np.float32,
    )
    assert np.allclose(direction_vector, expected)


def test_create_thrust_vector_from_direction_vector_uses_allocation_matrix(thrusters):
    thrusters.state.rov_config.thruster_allocation = np.array(
        [
            [1, 2, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, -1, 0, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0, 0],
        ],
        dtype=np.float32,
    )
    direction_vector = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.float32)

    thrust_vector = thrusters._create_thrust_vector_from_direction_vector(
        direction_vector
    )

    assert np.allclose(thrust_vector, np.array([5, -1, 5, 6, 7, 8, 1, 2]))


def test_create_thrust_vector_runs_full_default_pipeline(thrusters):
    thrusters.state.thrusters.direction_vector = np.array(
        [1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.75, -0.75],
        dtype=np.float32,
    )

    thrust_vector = thrusters._create_thrust_vector()

    assert np.allclose(
        thrust_vector,
        np.array(
            [-0.075, 0.675, -0.075, 0.075, 0.225, 0.375, 0.075, -0.675],
            dtype=np.float32,
        ),
    )
    assert np.allclose(
        thrusters.previous_direction_vector,
        np.array([1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.75, -0.75], dtype=np.float32),
    )
    assert thrusters.state.thrusters.work_indicator_percentage == 59


def test_correct_thrust_vector_spin_directions_applies_signs(thrusters):
    thrusters.state.rov_config.thruster_pin_setup = ThrusterPinSetup.model_validate(
        {
            "identifiers": [0, 1, 2, 3, 4, 5, 6, 7],
            "spinDirections": [1, -1, 1, -1, 1, -1, 1, -1],
        }
    )
    thrust_vector = np.ones(NUM_MOTORS, dtype=np.float32)

    thrusters._correct_thrust_vector_spin_directions(thrust_vector)

    assert np.array_equal(
        thrust_vector,
        np.array([1, -1, 1, -1, 1, -1, 1, -1], dtype=np.float32),
    )


def test_reorder_thrust_vector_reorders_by_identifiers(thrusters):
    thrusters.state.rov_config.thruster_pin_setup = ThrusterPinSetup.model_validate(
        {
            "identifiers": [7, 6, 5, 4, 3, 2, 1, 0],
            "spinDirections": [1, 1, 1, 1, 1, 1, 1, 1],
        }
    )
    thrust_vector = np.arange(NUM_MOTORS, dtype=np.float32)

    thrusters._reorder_thrust_vector(thrust_vector)

    assert np.array_equal(
        thrust_vector,
        np.array([7, 6, 5, 4, 3, 2, 1, 0], dtype=np.float32),
    )


def test_clip_thrust_vector_clamps_values_to_unit_range(thrusters):
    thrust_vector = np.array(
        [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0],
        dtype=np.float32,
    )

    thrusters._clip_thrust_vector(thrust_vector)

    assert np.allclose(
        thrust_vector,
        np.array([-1.0, -1.0, -0.5, 0.0, 0.5, 1.0, 1.0, 1.0], dtype=np.float32),
    )


def test_calculate_work_indicator_percentage_from_thrust_vector(thrusters):
    thrust_vector = np.array(
        [1.0, -0.5, 2.0, -2.0, 0.0, 0.25, -0.25, 0.75],
        dtype=np.float32,
    )

    percentage = thrusters._calculate_work_indicator_percentage_from_thrust_vector(
        thrust_vector
    )

    assert percentage == 59


def test_compute_thrust_values_maps_thrust_to_pulse_widths(thrusters):
    thrust_vector = np.array(
        [1.0, 0.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.0],
        dtype=np.float32,
    )

    thrust_values = thrusters._compute_thrust_values(thrust_vector)

    assert thrust_values == [
        THRUSTER_NEUTRAL_PULSE_WIDTH + THRUSTER_FORWARD_PULSE_RANGE,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
        THRUSTER_NEUTRAL_PULSE_WIDTH - THRUSTER_REVERSE_PULSE_RANGE,
        THRUSTER_NEUTRAL_PULSE_WIDTH + 500,
        THRUSTER_NEUTRAL_PULSE_WIDTH - 500,
        THRUSTER_NEUTRAL_PULSE_WIDTH + 250,
        THRUSTER_NEUTRAL_PULSE_WIDTH - 250,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
    ]


def test_compute_thrust_values_returns_neutral_for_all_zero_input(thrusters):
    thrust_values = thrusters._compute_thrust_values(
        np.zeros(NUM_MOTORS, dtype=np.float32)
    )

    assert thrust_values == [THRUSTER_NEUTRAL_PULSE_WIDTH] * NUM_MOTORS


def test_compute_thrust_values_returns_max_forward_for_full_positive_input(thrusters):
    thrust_values = thrusters._compute_thrust_values(
        np.ones(NUM_MOTORS, dtype=np.float32)
    )

    assert (
        thrust_values
        == [THRUSTER_NEUTRAL_PULSE_WIDTH + THRUSTER_FORWARD_PULSE_RANGE] * NUM_MOTORS
    )


def test_compute_thrust_values_pads_short_vectors_with_neutral(thrusters):
    thrust_values = thrusters._compute_thrust_values(
        np.array([1.0, -1.0, 0.5], dtype=np.float32)
    )

    assert thrust_values == [
        THRUSTER_NEUTRAL_PULSE_WIDTH + THRUSTER_FORWARD_PULSE_RANGE,
        THRUSTER_NEUTRAL_PULSE_WIDTH - THRUSTER_REVERSE_PULSE_RANGE,
        THRUSTER_NEUTRAL_PULSE_WIDTH + 500,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
        THRUSTER_NEUTRAL_PULSE_WIDTH,
    ]


def test_send_packet_writes_expected_binary_packet(thrusters):
    writer = _WriterSpy()
    thrust_values = [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700]

    asyncio.run(thrusters._send_packet(writer, thrust_values))

    expected = bytearray([THRUSTER_INPUT_START_BYTE]) + bytearray(
        struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
    )
    checksum = 0
    for value in expected:
        checksum ^= value
    expected.append(checksum)

    assert writer.writes == [bytes(expected)]
    assert writer.drains == 1


@pytest.mark.parametrize(
    ("protocol", "dshot_speed", "expected_protocol"),
    [("dshot", 300, MCU_PROTOCOL_DSHOT), ("pwm", 600, MCU_PROTOCOL_PWM)],
)
def test_send_config_packet_writes_expected_binary_packet(
    thrusters, protocol, dshot_speed, expected_protocol
):
    writer = _WriterSpy()
    thrusters.state.rov_config.thruster_protocol = protocol
    thrusters.state.rov_config.dshot_speed = dshot_speed

    asyncio.run(thrusters._send_config_packet(writer))

    expected = bytearray([MCU_CONFIG_START_BYTE, expected_protocol]) + bytearray(
        struct.pack("<H", dshot_speed)
    )
    checksum = 0
    for value in expected:
        checksum ^= value
    expected.append(checksum)

    assert writer.writes == [bytes(expected)]
    assert writer.drains == 1
