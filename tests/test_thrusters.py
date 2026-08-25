import asyncio
import struct
from typing import Any, cast

import numpy as np
import pytest

from rov_firmware import thrusters as thrusters_module
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
from rov_firmware.websocket.receive.actions import handle_start_thruster_test


class _WriterSpy:
    def __init__(self):
        self.writes = []
        self.drains = 0

    def write(self, data):
        self.writes.append(bytes(data))

    async def drain(self):
        self.drains += 1


class _SerialManagerSpy:
    def __init__(self):
        self.connection_generation = 1
        self.mcu_protocol_config: tuple[str, int] | None = None
        self.write_lock = asyncio.Lock()


@pytest.fixture
def thrusters(rov_state):
    return Thrusters(
        rov_state,
        cast(Any, _SerialManagerSpy()),
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


def test_stale_input_still_stops_thrusters_with_stabilization_enabled(thrusters):
    thrusters.state.system_status.auto_stabilization = True
    thrusters.state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
    thrusters.state.thrusters.last_direction_time = 0.0

    thrust_vector, _, _ = thrusters._determine_thrust_vector(100.0, 99.0)

    assert thrust_vector is not None
    assert np.array_equal(thrust_vector, np.zeros(8, dtype=np.float32))


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


def test_send_packet_waits_for_exclusive_serial_writer(thrusters):
    writer = _WriterSpy()

    async def run_test() -> None:
        await thrusters.serial_manager.write_lock.acquire()
        send = asyncio.create_task(thrusters._send_packet(writer, [1500] * NUM_MOTORS))
        await asyncio.sleep(0)
        assert writer.writes == []
        thrusters.serial_manager.write_lock.release()
        await send

    asyncio.run(run_test())

    assert len(writer.writes) == 1


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


def test_protocol_config_holds_neutral_until_mcu_acknowledges(rov_state):
    serial_manager = _SerialManagerSpy()
    thrusters = Thrusters(
        rov_state,
        cast(Any, serial_manager),
        cast(Any, RegulatorController(rov_state)),
    )
    writer = _WriterSpy()

    confirmed = asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))

    neutral_payload = struct.pack(
        f"<{NUM_MOTORS}H", *([THRUSTER_NEUTRAL_PULSE_WIDTH] * NUM_MOTORS)
    )
    assert confirmed is False
    assert writer.writes[0][1:-1] == neutral_payload
    assert writer.writes[1][0] == MCU_CONFIG_START_BYTE

    serial_manager.mcu_protocol_config = ("dshot", 300)
    writer.writes.clear()

    confirmed = asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))

    assert confirmed is True
    assert writer.writes == []


def test_protocol_config_retries_after_unacknowledged_attempt(rov_state):
    serial_manager = _SerialManagerSpy()
    thrusters = Thrusters(
        rov_state,
        cast(Any, serial_manager),
        cast(Any, RegulatorController(rov_state)),
    )
    writer = _WriterSpy()

    asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))
    thrusters._last_config_attempt_time -= 1
    writer.writes.clear()

    confirmed = asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))

    assert confirmed is False
    assert len(writer.writes) == 2
    assert writer.writes[0][0] == THRUSTER_INPUT_START_BYTE
    assert writer.writes[1][0] == MCU_CONFIG_START_BYTE


def test_protocol_config_logs_actionable_error_when_ack_stays_blocked(
    rov_state, monkeypatch
):
    serial_manager = _SerialManagerSpy()
    thrusters = Thrusters(
        rov_state,
        cast(Any, serial_manager),
        cast(Any, RegulatorController(rov_state)),
    )
    writer = _WriterSpy()
    messages: list[str] = []
    monkeypatch.setattr(thrusters_module, "log_error", messages.append)

    asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))
    thrusters._pending_config_since -= 6
    asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))
    asyncio.run(thrusters._ensure_config_sent(cast(Any, writer)))

    assert messages == [
        "Thruster protocol change is still blocked because the MCU has not "
        "confirmed it. Check the MCU connection and firmware."
    ]


def test_thruster_test_countdown_starts_after_first_command_write(
    thrusters, monkeypatch
):
    toasts = []
    monkeypatch.setattr(
        thrusters_module, "toast_content", lambda **kwargs: toasts.append(kwargs)
    )
    thrusters.state.thrusters.test_thruster = 3

    vector = thrusters._handle_thruster_test(100.0, 3)

    assert vector is not None
    assert vector[3] == pytest.approx(0.1)
    assert thrusters.state.thrusters.test_start_time is None
    assert toasts == []

    thrusters._mark_thruster_test_started(
        100.0, thrusters.state.thrusters.test_request_id
    )

    assert thrusters.state.thrusters.test_start_time == 100.0
    assert thrusters.state.thrusters.last_remaining == 10
    assert toasts[0]["variant"].value == "loading"
    assert toasts[0]["content"].description_args == {"seconds": 10}


def test_unrelated_write_cannot_start_test_queued_while_drain_yields(
    thrusters, monkeypatch
):
    toasts = []
    monkeypatch.setattr(
        thrusters_module, "toast_content", lambda **kwargs: toasts.append(kwargs)
    )
    thrusters.state.system_status.thruster_control_ready = True

    async def run_interleaving() -> None:
        vector, _, selected_request_id = thrusters._determine_thrust_vector(100.0, 0.0)
        assert vector is not None
        thrust_values = thrusters._compute_thrust_values(vector)

        class _InterleavingWriter(_WriterSpy):
            async def drain(self):
                await asyncio.sleep(0)
                await handle_start_thruster_test(thrusters.state, 3)
                await super().drain()

        sent = await thrusters._send_with_retries(
            cast(Any, _InterleavingWriter()), thrust_values
        )
        assert sent is True
        thrusters._mark_thruster_test_started(100.0, selected_request_id)

        assert thrusters.state.thrusters.test_thruster == 3
        assert thrusters.state.thrusters.test_start_time is None
        assert toasts == []

        test_vector, _, test_request_id = thrusters._determine_thrust_vector(101.0, 0.0)
        assert test_vector is not None
        sent = await thrusters._send_with_retries(
            cast(Any, _WriterSpy()), thrusters._compute_thrust_values(test_vector)
        )
        assert sent is True
        thrusters._mark_thruster_test_started(101.0, test_request_id)

    asyncio.run(run_interleaving())

    assert thrusters.state.thrusters.test_start_time == 101.0
    assert toasts[0]["content"].description_args == {"seconds": 10}


def test_lost_readiness_ends_thruster_test_with_terminal_error(thrusters, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        thrusters_module, "toast_content", lambda **kwargs: toasts.append(kwargs)
    )
    thrusters.state.thrusters.test_thruster = 2
    thrusters.state.thrusters.test_start_time = 50.0

    thrusters._fail_thruster_test_unavailable()

    assert thrusters.state.thrusters.test_thruster is None
    assert thrusters.state.thrusters.test_start_time is None
    assert toasts[0]["variant"].value == "error"
    assert toasts[0]["content"].message_key == "toasts_thruster_test_unavailable"
