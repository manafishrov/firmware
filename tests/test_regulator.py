import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from rov_firmware.constants import (
    DEPTH_DERIVATIVE_EMA_TAU,
    DEPTH_INTEGRAL_WINDUP_CLIP,
    INTEGRAL_RELAX_THRESHOLD,
    MAX_GYRO_DEG_PER_SEC,
    THRUSTER_SEND_FREQUENCY,
)
from rov_firmware.models.config import AxisConfig
from rov_firmware.regulator import (
    Regulator as RegulatorController,
    _clamp_dt,
    _MahonyAhrs,
)


@pytest.mark.parametrize(
    ("raw_dt", "expected_dt"),
    [
        (1 / THRUSTER_SEND_FREQUENCY, 1 / THRUSTER_SEND_FREQUENCY),
        (0.0, (1 / THRUSTER_SEND_FREQUENCY) * 0.5),
        (-1.0, (1 / THRUSTER_SEND_FREQUENCY) * 0.5),
        (np.inf, 1 / THRUSTER_SEND_FREQUENCY),
        (np.nan, 1 / THRUSTER_SEND_FREQUENCY),
        ((1 / THRUSTER_SEND_FREQUENCY) * 0.49, (1 / THRUSTER_SEND_FREQUENCY) * 0.5),
        ((1 / THRUSTER_SEND_FREQUENCY) * 0.5, (1 / THRUSTER_SEND_FREQUENCY) * 0.5),
        ((1 / THRUSTER_SEND_FREQUENCY) * 10.0, (1 / THRUSTER_SEND_FREQUENCY) * 10.0),
        ((1 / THRUSTER_SEND_FREQUENCY) * 10.1, (1 / THRUSTER_SEND_FREQUENCY) * 10.0),
    ],
)
def test_clamp_dt(raw_dt, expected_dt):
    assert _clamp_dt(raw_dt) == pytest.approx(expected_dt)


def test_mahony_reset_zeroes_internal_state():
    ahrs = _MahonyAhrs(kp=1.0, ki=0.5)
    ahrs._integral[:] = np.array([1.0, -2.0, 3.0], dtype=np.float32)
    ahrs.current_attitude = Rotation.from_euler("ZYX", [10.0, -5.0, 2.0], degrees=True)

    ahrs.reset()

    assert np.allclose(ahrs._integral, np.zeros(3, dtype=np.float32))
    assert np.allclose(ahrs.current_attitude.as_quat(), Rotation.identity().as_quat())


def test_mahony_update_with_valid_accel_and_gyro_changes_attitude():
    ahrs = _MahonyAhrs(kp=1.5, ki=0.05)

    ahrs.update(
        np.array([0.2, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, -9.81], dtype=np.float32),
        1 / THRUSTER_SEND_FREQUENCY,
    )

    assert not np.allclose(
        ahrs.current_attitude.as_quat(), Rotation.identity().as_quat()
    )


def test_mahony_update_with_zero_accel_norm_falls_back_to_gyro_only():
    gyro = np.array([0.05, -0.02, 0.01], dtype=np.float32)
    ahrs = _MahonyAhrs(kp=1.5, ki=0.05)

    ahrs.update(gyro.copy(), np.zeros(3, dtype=np.float32), 0.01)

    expected = Rotation.from_rotvec(gyro * _clamp_dt(0.01))
    assert np.allclose(ahrs.current_attitude.as_rotvec(), expected.as_rotvec())


def test_mahony_update_discards_unreasonably_large_gyro():
    gyro = np.array(
        [np.deg2rad(MAX_GYRO_DEG_PER_SEC + 1.0), 0.0, 0.0],
        dtype=np.float32,
    )
    ahrs = _MahonyAhrs(kp=1.5, ki=0.05)

    ahrs.update(gyro, np.array([0.0, 0.0, -9.81], dtype=np.float32), 0.01)

    assert np.allclose(gyro, np.zeros(3, dtype=np.float32))
    assert np.allclose(ahrs.current_attitude.as_quat(), Rotation.identity().as_quat())


def test_mahony_quaternion_stays_normalized_after_many_updates():
    ahrs = _MahonyAhrs(kp=1.5, ki=0.05)
    gyro = np.array([0.03, -0.01, 0.02], dtype=np.float32)
    accel = np.array([0.0, 0.0, -9.81], dtype=np.float32)

    for _ in range(50):
        ahrs.update(gyro.copy(), accel, 1 / THRUSTER_SEND_FREQUENCY)

    assert np.linalg.norm(ahrs.current_attitude.as_quat()) == pytest.approx(1.0)


def test_handle_depth_hold_computes_pid_and_updates_filtered_derivative(rov_state):
    state = rov_state
    state.rov_config.regulator.depth = AxisConfig(kp=2.0, ki=3.0, kd=4.0, rate=1.0)
    state.pressure.depth = 7.0
    state.regulator.desired_depth = 10.0
    regulator = RegulatorController(state)
    regulator.delta_t_run_regulator = 0.1
    regulator.integral_depth = 0.5
    regulator.previous_depth = 6.0
    regulator.current_dt_depth = 1.2

    actuation = regulator._handle_depth_hold(np.float32(0.25))

    error = 3.0
    expected_integral = 0.5 + error * 0.1 * 0.75
    alpha = float(np.exp(-0.1 / DEPTH_DERIVATIVE_EMA_TAU))
    expected_rate = alpha * 1.2 + (1.0 - alpha) * 10.0
    expected_actuation = 2.0 * error + 3.0 * expected_integral + 4.0 * expected_rate

    assert regulator.integral_depth == pytest.approx(expected_integral)
    assert regulator.current_dt_depth == pytest.approx(expected_rate)
    assert regulator.previous_depth == pytest.approx(7.0)
    assert actuation == pytest.approx(expected_actuation)


def test_handle_depth_hold_clips_integral_windup(rov_state):
    state = rov_state
    state.pressure.depth = 0.0
    state.regulator.desired_depth = 100.0
    regulator = RegulatorController(state)
    regulator.delta_t_run_regulator = 1.0

    regulator._handle_depth_hold(np.float32(0.0))

    assert regulator.integral_depth == pytest.approx(DEPTH_INTEGRAL_WINDUP_CLIP)


def test_handle_stabilization_computes_pid_per_axis(rov_state):
    state = rov_state
    state.rov_config.regulator.pitch = AxisConfig(kp=2.0, ki=3.0, kd=4.0, rate=1.0)
    state.rov_config.regulator.yaw = AxisConfig(kp=5.0, ki=6.0, kd=7.0, rate=1.0)
    state.rov_config.regulator.roll = AxisConfig(kp=8.0, ki=9.0, kd=10.0, rate=1.0)
    regulator = RegulatorController(state)
    regulator.delta_t_run_regulator = 0.2
    regulator.ahrs.current_attitude = Rotation.identity()
    regulator.desired_attitude = Rotation.from_rotvec(
        np.array([0.3, -0.2, 0.1], dtype=np.float32)
    )
    regulator.gyro_rad_s[:] = np.array([0.5, -0.25, 0.75], dtype=np.float32)

    stabilization = regulator._handle_stabilization(np.zeros(3, dtype=np.float32))

    expected_integral = np.array([0.06, -0.04, 0.02], dtype=np.float32)
    expected = np.array(
        [
            (-0.4 - 0.12 + 1.0) / 10.0,
            (0.5 + 0.12 - 5.25) / 10.0,
            (2.4 + 0.54 - 5.0) / 10.0,
        ],
        dtype=np.float32,
    )

    assert np.allclose(regulator.integral_attitude_rad, expected_integral)
    assert np.allclose(stabilization, expected)


def test_handle_stabilization_relaxes_integral_when_user_is_commanding(rov_state):
    state = rov_state
    regulator = RegulatorController(state)
    regulator.delta_t_run_regulator = 0.2
    regulator.ahrs.current_attitude = Rotation.identity()
    regulator.desired_attitude = Rotation.from_rotvec(
        np.array([0.2, 0.1, -0.1], dtype=np.float32)
    )
    regulator.integral_attitude_rad[:] = np.array([0.1, -0.2, 0.3], dtype=np.float32)

    regulator._handle_stabilization(
        np.array([INTEGRAL_RELAX_THRESHOLD + 0.01, 0.0, 0.0], dtype=np.float32)
    )

    assert np.allclose(
        regulator.integral_attitude_rad,
        np.array([0.1, -0.2, 0.3], dtype=np.float32),
    )


def test_transform_movement_vector_world_to_body_is_identity_for_level_attitude(
    rov_state,
):
    state = rov_state
    regulator = RegulatorController(state)
    regulator.ahrs.current_attitude = Rotation.identity()
    movement = np.array([1.0, -0.5, 0.25], dtype=np.float32)

    transformed = regulator._transform_movement_vector_world_to_body(movement)

    assert np.allclose(transformed, movement)


def test_transform_movement_vector_world_to_body_applies_known_rotation(rov_state):
    state = rov_state
    regulator = RegulatorController(state)
    regulator.ahrs.current_attitude = Rotation.from_euler(
        "ZYX", [0.0, 0.0, 90.0], degrees=True
    )

    transformed = regulator._transform_movement_vector_world_to_body(
        np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )

    assert np.allclose(transformed, np.array([0.0, 0.0, -1.0], dtype=np.float32))


def test_scale_direction_vector_with_user_max_power_scales_thrusters_and_actions_separately(
    rov_state,
):
    state = rov_state
    state.rov_config.power.thrusters_limit = 40
    state.rov_config.power.actions_limit = 25
    regulator = RegulatorController(state)
    direction_vector = np.array(
        [1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 1.0, -1.0],
        dtype=np.float32,
    )

    regulator._scale_direction_vector_with_user_max_power(direction_vector)

    assert np.allclose(
        direction_vector,
        np.array([0.4, -0.4, 0.2, -0.2, 0.1, -0.1, 0.25, -0.25], dtype=np.float32),
    )


def test_scale_regulator_direction_vector_clips_to_power_limit(rov_state):
    state = rov_state
    state.rov_config.power.regulator_limit = 30
    regulator = RegulatorController(state)
    regulator_direction_vector = np.array(
        [-1.0, -0.2, 0.0, 0.2, 0.6, 1.0, -0.7, 0.7],
        dtype=np.float32,
    )

    regulator._scale_regulator_direction_vector(regulator_direction_vector)

    assert np.allclose(
        regulator_direction_vector,
        np.array([-0.3, -0.2, 0.0, 0.2, 0.3, 0.3, -0.3, 0.3], dtype=np.float32),
    )
