"""Regulator module for ROV control (TEST VERSION: self-contained new params/state)."""

from __future__ import annotations

import time
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import curve_fit  # kept to avoid touching your imports
from scipy.spatial.transform import Rotation as R

from .constants import (
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEGREES,
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEPTH_METERS,
    AUTO_TUNING_OSCILLATION_DURATION_SECONDS,
    AUTO_TUNING_TOAST_ID,
    AUTO_TUNING_ZERO_THRESHOLD_DEGREES,
    AUTO_TUNING_ZERO_THRESHOLD_DEPTH_METERS,
    COMPLEMENTARY_FILTER_ALPHA,  # unused in this rewrite, kept for compatibility
    DEPTH_DERIVATIVE_EMA_TAU,
    INTEGRAL_WINDUP_CLIP_DEGREES,
    PITCH_MAX,
    ROLL_UPSIDE_DOWN_THRESHOLD,  # unused in this rewrite, kept for compatibility
    ROLL_WRAP_MAX,
)
from .log import log_error, log_info
from .models.config import (
    RegulatorPID,
    RegulatorSuggestions as RegulatorSuggestionsPayload,
)
from .rov_state import RovState
from .toast import toast_loading, toast_success
from .websocket.message import RegulatorSuggestions
from .websocket.queue import get_message_queue


# =============================================================================
# TEST TUNABLES (edit here; no changes required elsewhere in your codebase)
# =============================================================================

# AHRS (Mahony) gains
TEST_AHRS_MAHONY_KP: float = 2.5
TEST_AHRS_MAHONY_KI: float = 0.05
TEST_AHRS_ACCEL_MIN_NORM: float = 1e-3

# dt guards
TEST_DT_MIN_SECONDS: float = 1e-3
TEST_DT_MAX_SECONDS: float = 0.1

# Depth hold behavior
TEST_DEPTH_INTEGRAL_WINDUP_CLIP: float = 3.0
TEST_DEPTH_HOLD_SETPOINT_RATE_MPS: float = 0.6          # heave stick -> depth target rate
TEST_DEPTH_HOLD_ENABLE_RAMP_SECONDS: float = 0.5        # smooth ramp on enable

# Yaw stabilization (can be enabled without adding system_status.yaw_stabilization)
TEST_ENABLE_YAW_STABILIZATION: bool = True

# Yaw PID gains (kept inside this file; independent from config)
TEST_YAW_KP: float = 2.0
TEST_YAW_KI: float = 0.0
TEST_YAW_KD: float = 0.2


def _wrap_angle_deg(angle: float) -> float:
    """Wrap to [-180, 180)."""
    return ((angle + 180.0) % 360.0) - 180.0


def _angle_error_deg(target: float, current: float) -> float:
    """Shortest signed error target-current in degrees, wrapped to [-180, 180)."""
    return _wrap_angle_deg(target - current)


def _clamp_dt(dt: float) -> float:
    if not np.isfinite(dt):
        return 0.0167
    return float(np.clip(dt, TEST_DT_MIN_SECONDS, TEST_DT_MAX_SECONDS))


class _MahonyAhrs:
    """
    Mahony AHRS (gyro + accel) in quaternion form.

    - Stabilizes roll/pitch with accel (gravity).
    - Yaw is integrated from gyro (will drift without external heading reference).
    """

    def __init__(self, kp: float, ki: float) -> None:
        self.kp = float(kp)
        self.ki = float(ki)
        self._integral: NDArray[np.float64] = np.zeros(3, dtype=np.float64)
        self._q: R = R.identity()

    @property
    def rotation_body_to_world(self) -> R:
        return self._q

    def reset(self) -> None:
        self._integral[:] = 0.0
        self._q = R.identity()

    def update(
        self,
        gyro_rad_s: NDArray[np.float32],
        accel: NDArray[np.float32],
        dt: float,
    ) -> None:
        dt = _clamp_dt(dt)

        ax, ay, az = float(accel[0]), float(accel[1]), float(accel[2])
        a_norm = float(np.sqrt(ax * ax + ay * ay + az * az))
        if not np.isfinite(a_norm) or a_norm < TEST_AHRS_ACCEL_MIN_NORM:
            self._integrate_gyro_only(gyro_rad_s, dt)
            return

        a = np.array([ax, ay, az], dtype=np.float64) / a_norm

        # Estimated "up" direction in body frame from current attitude:
        g_body = self._q.inv().apply(np.array([0.0, 0.0, 1.0], dtype=np.float64))

        # Error drives estimated up toward measured accel direction.
        # If your signs come out inverted, flip a -> -a here once.
        e = np.cross(a, g_body)

        if self.ki > 0.0:
            self._integral += e * (self.ki * dt)

        omega = np.array(
            [
                float(gyro_rad_s[0]) + self.kp * e[0] + self._integral[0],
                float(gyro_rad_s[1]) + self.kp * e[1] + self._integral[1],
                float(gyro_rad_s[2]) + self.kp * e[2] + self._integral[2],
            ],
            dtype=np.float64,
        )

        self._integrate_omega(omega, dt)

    def _integrate_gyro_only(self, gyro_rad_s: NDArray[np.float32], dt: float) -> None:
        omega = np.array(
            [float(gyro_rad_s[0]), float(gyro_rad_s[1]), float(gyro_rad_s[2])],
            dtype=np.float64,
        )
        self._integrate_omega(omega, dt)

    def _integrate_omega(self, omega_rad_s: NDArray[np.float64], dt: float) -> None:
        dtheta = omega_rad_s * float(dt)
        dR = R.from_rotvec(dtheta)
        self._q = self._q * dR  # body-to-world update

        q = self._q.as_quat()
        q /= np.linalg.norm(q)
        self._q = R.from_quat(q)


class Regulator:
    """PID regulator for ROV stabilization."""

    def __init__(self, state: RovState):
        self.state: RovState = state

        self.gyro: NDArray[np.float32] = np.array([0.0, 0.0, 0.0], dtype=np.float32)  # deg/s
        self.last_measurement_time: float = 0.0
        self.delta_t: float = 0.0167

        self.previous_depth: float = 0.0
        self.current_dt_depth: float = 0.0

        # Quaternion attitude estimator
        self._ahrs: _MahonyAhrs = _MahonyAhrs(kp=TEST_AHRS_MAHONY_KP, ki=TEST_AHRS_MAHONY_KI)
        self._attitude_initialized: bool = False

        # Internal yaw state (so you don't need to add state.regulator.yaw/desired_yaw/integral_yaw yet)
        self._yaw_deg: float = 0.0
        self._desired_yaw_deg: float = 0.0
        self._integral_yaw_deg: float = 0.0

        # Edge detection for bumpless transfer and ramp-in
        self._prev_depth_hold: bool = False
        self._prev_pitch_stab: bool = False
        self._prev_roll_stab: bool = False
        self._prev_yaw_stab: bool = False

        self._depth_hold_enabled_time: float = 0.0

        # Auto tuning fields (kept as-is)
        self.auto_tuning_phase: str = ""
        self.auto_tuning_step: str = ""
        self.auto_tuning_data: list[tuple[float, float]] = []
        self.auto_tuning_params: dict[str, RegulatorPID] = {}
        self.auto_tuning_last_update: float = 0.0
        self.auto_tuning_zero_actuation: float = 0.0
        self.auto_tuning_amplitude: float = 0.0
        self.auto_tuning_oscillation_start: float = 0.0

    def _yaw_stab_enabled(self) -> bool:
        # Prefer real flag if you add it later; otherwise use test toggle.
        return bool(getattr(self.state.system_status, "yaw_stabilization", TEST_ENABLE_YAW_STABILIZATION))

    def _normalize_angles(self, pitch: float, roll: float, yaw: float) -> tuple[float, float, float]:
        roll = _wrap_angle_deg(roll)
        yaw = _wrap_angle_deg(yaw)
        pitch = float(np.clip(pitch, -PITCH_MAX, PITCH_MAX))
        return pitch, roll, yaw

    def _get_rotation_body_to_world(self) -> R:
        return self._ahrs.rotation_body_to_world

    # -------------------------------------------------------------------------
    # Public API (must keep name/signature): update_desired_from_direction_vector
    # -------------------------------------------------------------------------
    def update_desired_from_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Update desired pitch/roll/yaw from direction vector."""
        config = self.state.rov_config.regulator

        if self.state.system_status.pitch_stabilization:
            pitch_change = float(direction_vector[3])
            desired_pitch = float(self.state.regulator.desired_pitch) + pitch_change * float(config.turn_speed) * self.delta_t
            self.state.regulator.desired_pitch = float(np.clip(desired_pitch, -PITCH_MAX, PITCH_MAX))

        if self.state.system_status.roll_stabilization:
            roll_change = float(direction_vector[5])
            desired_roll = float(self.state.regulator.desired_roll) + roll_change * float(config.turn_speed) * self.delta_t
            desired_roll = _wrap_angle_deg(desired_roll)

            current_roll = float(self.state.regulator.roll)
            if desired_roll - current_roll > ROLL_WRAP_MAX:
                desired_roll -= 360.0
            if desired_roll - current_roll < -ROLL_WRAP_MAX:
                desired_roll += 360.0
            self.state.regulator.desired_roll = float(desired_roll)

        if self._yaw_stab_enabled():
            yaw_change = float(direction_vector[4])
            self._desired_yaw_deg = _wrap_angle_deg(self._desired_yaw_deg + yaw_change * float(config.turn_speed) * self.delta_t)

    # -------------------------------------------------------------------------
    # Public API (must keep name/signature): update_regulator_data_from_imu
    # -------------------------------------------------------------------------
    def update_regulator_data_from_imu(self) -> None:
        """Update regulator data from IMU readings (quaternion AHRS)."""
        if not self.state.system_health.imu_ok:
            return

        imu_data = self.state.imu
        accel = cast(NDArray[np.float32], imu_data.acceleration)
        gyr = cast(NDArray[np.float32], imu_data.gyroscope)  # rad/s

        self.gyro = np.degrees(gyr).astype(np.float32)

        now = time.time()
        if self.last_measurement_time > 0.0:
            self.delta_t = _clamp_dt(now - self.last_measurement_time)
        else:
            self.delta_t = 0.0167
        self.last_measurement_time = now

        if not self._attitude_initialized:
            ax, ay, az = float(accel[0]), float(accel[1]), float(accel[2])
            a_norm = float(np.sqrt(ax * ax + ay * ay + az * az))
            if np.isfinite(a_norm) and a_norm > TEST_AHRS_ACCEL_MIN_NORM:
                a = np.array([ax, ay, az], dtype=np.float64) / a_norm
                z_world = np.array([0.0, 0.0, 1.0], dtype=np.float64)
                v = np.cross(a, z_world)
                s = float(np.linalg.norm(v))
                c = float(np.dot(a, z_world))
                self._ahrs.reset()
                if s > 1e-9:
                    axis = v / s
                    angle = float(np.arctan2(s, c))
                    self._ahrs._q = R.from_rotvec(axis * angle)  # pylint: disable=protected-access
                self._attitude_initialized = True

        self._ahrs.update(gyr, accel, self.delta_t)

        rot = self._get_rotation_body_to_world()
        roll, pitch, yaw = rot.as_euler("xyz", degrees=True)
        pitch, roll, yaw = self._normalize_angles(float(pitch), float(roll), float(yaw))

        self.state.regulator.pitch = pitch
        self.state.regulator.roll = roll

        # Keep yaw internally; if you later add state.regulator.yaw, it will start updating automatically.
        self._yaw_deg = yaw
        if hasattr(self.state.regulator, "yaw"):
            setattr(self.state.regulator, "yaw", yaw)

    # -------------------------------------------------------------------------
    # Depth hold internals
    # -------------------------------------------------------------------------
    def _depth_hold_enable_edge(self) -> None:
        current_depth = float(self.state.pressure.depth)
        self.state.regulator.desired_depth = current_depth
        self.state.regulator.integral_depth = 0.0
        self.current_dt_depth = 0.0
        self.previous_depth = current_depth
        self._depth_hold_enabled_time = time.time()

    def _depth_hold_ramp(self) -> float:
        if not self.state.system_status.depth_hold:
            return 1.0
        t = time.time() - self._depth_hold_enabled_time
        return float(np.clip(t / TEST_DEPTH_HOLD_ENABLE_RAMP_SECONDS, 0.0, 1.0))

    def _handle_depth_hold_setpoint(self, heave_input: float) -> None:
        if not self.state.system_status.depth_hold:
            return
        desired_depth = float(self.state.regulator.desired_depth)
        desired_depth += (-float(heave_input)) * TEST_DEPTH_HOLD_SETPOINT_RATE_MPS * self.delta_t
        self.state.regulator.desired_depth = float(desired_depth)

    def _handle_depth_hold(self, heave_input: float) -> float:
        if not self.state.system_status.depth_hold:
            return 0.0

        current_depth = float(self.state.pressure.depth)
        desired_depth = float(self.state.regulator.desired_depth)

        error = current_depth - desired_depth  # positive => too deep => command up

        integral_scale = float(np.clip((1.0 - abs(float(heave_input))), 0.0, 1.0))
        self.state.regulator.integral_depth += error * self.delta_t * integral_scale
        self.state.regulator.integral_depth = float(
            np.clip(self.state.regulator.integral_depth, -TEST_DEPTH_INTEGRAL_WINDUP_CLIP, TEST_DEPTH_INTEGRAL_WINDUP_CLIP)
        )

        alpha = float(np.exp(-self.delta_t / float(DEPTH_DERIVATIVE_EMA_TAU)))
        raw_rate = (current_depth - self.previous_depth) / self.delta_t
        self.current_dt_depth = alpha * self.current_dt_depth + (1.0 - alpha) * float(raw_rate)
        self.previous_depth = current_depth

        config = self.state.rov_config.regulator
        heave_cmd = (
            float(config.depth.kp) * error
            + float(config.depth.ki) * float(self.state.regulator.integral_depth)
            + float(config.depth.kd) * float(self.current_dt_depth)
        )
        return float(heave_cmd) * self._depth_hold_ramp()

    # -------------------------------------------------------------------------
    # Attitude stabilization internals
    # -------------------------------------------------------------------------
    def _attitude_enable_edge(self) -> None:
        self.state.regulator.desired_pitch = float(self.state.regulator.pitch)
        self.state.regulator.desired_roll = float(self.state.regulator.roll)
        self._desired_yaw_deg = float(self._yaw_deg)

        self.state.regulator.integral_pitch = 0.0
        self.state.regulator.integral_roll = 0.0
        self._integral_yaw_deg = 0.0

    def _handle_pitch_stabilization(self, pitch_actuation_input: float) -> float:
        if not self.state.system_status.pitch_stabilization:
            return 0.0

        config = self.state.rov_config.regulator
        desired_pitch = float(self.state.regulator.desired_pitch)
        current_pitch = float(self.state.regulator.pitch)

        err_deg = desired_pitch - current_pitch
        integral_scale = float(np.clip((1.0 - abs(float(pitch_actuation_input))), 0.0, 1.0))
        self.state.regulator.integral_pitch += err_deg * self.delta_t * integral_scale
        self.state.regulator.integral_pitch = float(
            np.clip(self.state.regulator.integral_pitch, -INTEGRAL_WINDUP_CLIP_DEGREES, INTEGRAL_WINDUP_CLIP_DEGREES)
        )

        gyro_pitch_deg_s = float(self.gyro[1])
        return float(
            float(config.pitch.kp) * float(np.radians(err_deg))
            + float(config.pitch.ki) * float(np.radians(float(self.state.regulator.integral_pitch)))
            - float(config.pitch.kd) * float(np.radians(gyro_pitch_deg_s))
        )

    def _handle_roll_stabilization(self, roll_actuation_input: float) -> float:
        if not self.state.system_status.roll_stabilization:
            return 0.0

        config = self.state.rov_config.regulator
        desired_roll = float(self.state.regulator.desired_roll)
        current_roll = float(self.state.regulator.roll)

        err_deg = _angle_error_deg(desired_roll, current_roll)
        integral_scale = float(np.clip((1.0 - abs(float(roll_actuation_input))), 0.0, 1.0))
        self.state.regulator.integral_roll += err_deg * self.delta_t * integral_scale
        self.state.regulator.integral_roll = float(
            np.clip(self.state.regulator.integral_roll, -INTEGRAL_WINDUP_CLIP_DEGREES, INTEGRAL_WINDUP_CLIP_DEGREES)
        )

        gyro_roll_deg_s = float(self.gyro[0])
        return float(
            float(config.roll.kp) * float(np.radians(err_deg))
            + float(config.roll.ki) * float(np.radians(float(self.state.regulator.integral_roll)))
            - float(config.roll.kd) * float(np.radians(gyro_roll_deg_s))
        )

    def _handle_yaw_stabilization(self, yaw_actuation_input: float) -> float:
        if not self._yaw_stab_enabled():
            return 0.0

        err_deg = _angle_error_deg(self._desired_yaw_deg, self._yaw_deg)

        integral_scale = float(np.clip((1.0 - abs(float(yaw_actuation_input))), 0.0, 1.0))
        self._integral_yaw_deg += err_deg * self.delta_t * integral_scale
        self._integral_yaw_deg = float(
            np.clip(self._integral_yaw_deg, -INTEGRAL_WINDUP_CLIP_DEGREES, INTEGRAL_WINDUP_CLIP_DEGREES)
        )

        gyro_yaw_deg_s = float(self.gyro[2])
        return float(
            TEST_YAW_KP * float(np.radians(err_deg))
            + TEST_YAW_KI * float(np.radians(self._integral_yaw_deg))
            - TEST_YAW_KD * float(np.radians(gyro_yaw_deg_s))
        )

    # -------------------------------------------------------------------------
    # Frame transforms using quaternion attitude and direction coefficients
    # -------------------------------------------------------------------------
    def _solve_body_vector_from_world(
        self,
        world_vec: NDArray[np.float64],
        coeffs: NDArray[np.float64],
    ) -> NDArray[np.float32]:
        rot = self._get_rotation_body_to_world()
        rmat = rot.as_matrix().astype(np.float64)

        c = coeffs.copy()
        for i in range(3):
            if not np.isfinite(c[i]) or c[i] == 0.0:
                c[i] = 1.0

        a = rmat @ np.diag(c)
        b = world_vec

        try:
            u = np.linalg.solve(a, b)
        except np.linalg.LinAlgError:
            u, *_ = np.linalg.lstsq(a, b, rcond=None)

        return u.astype(np.float32)

    def _transform_translation_for_depth_hold(self, direction_vector: NDArray[np.float32]) -> None:
        if not self.state.system_status.depth_hold:
            return

        dir_coeffs = self.state.rov_config.direction_coefficients
        surge_coeff = float(getattr(dir_coeffs, "surge", 1.0)) or 1.0
        sway_coeff = float(getattr(dir_coeffs, "sway", 1.0)) or 1.0
        heave_coeff = float(getattr(dir_coeffs, "heave", 1.0)) or 1.0

        surge_in = float(direction_vector[0])
        sway_in = float(direction_vector[1])

        yaw = float(self._yaw_deg)
        r_yaw = R.from_euler("z", yaw, degrees=True)

        world_vel = r_yaw.apply(np.array([surge_coeff * surge_in, sway_coeff * sway_in, 0.0], dtype=np.float64))

        u_body = self._solve_body_vector_from_world(
            world_vel.astype(np.float64),
            np.array([surge_coeff, sway_coeff, heave_coeff], dtype=np.float64),
        )

        direction_vector[0] = float(u_body[0])
        direction_vector[1] = float(u_body[1])
        direction_vector[2] = 0.0  # heave input is setpoint nudging

    def _transform_world_orientation_to_body(self, direction_vector: NDArray[np.float32]) -> None:
        dir_coeffs = self.state.rov_config.direction_coefficients
        pitch_coeff = float(getattr(dir_coeffs, "pitch", 1.0)) or 1.0
        yaw_coeff = float(getattr(dir_coeffs, "yaw", 1.0)) or 1.0
        roll_coeff = float(getattr(dir_coeffs, "roll", 1.0)) or 1.0

        pitch_w = float(direction_vector[3])
        yaw_w = float(direction_vector[4])
        roll_w = float(direction_vector[5])

        omega_world = np.array(
            [roll_coeff * roll_w, pitch_coeff * pitch_w, yaw_coeff * yaw_w],
            dtype=np.float64,
        )

        u_body_xyz = self._solve_body_vector_from_world(
            omega_world,
            np.array([roll_coeff, pitch_coeff, yaw_coeff], dtype=np.float64),
        )

        direction_vector[3] = float(u_body_xyz[1])  # pitch
        direction_vector[4] = float(u_body_xyz[2])  # yaw
        direction_vector[5] = float(u_body_xyz[0])  # roll

    # -------------------------------------------------------------------------
    # Scaling/clipping (kept consistent with your behavior)
    # -------------------------------------------------------------------------
    def _scale_direction_vector_with_user_max_power(self, direction_vector: NDArray[np.float32]) -> None:
        scale = float(self.state.rov_config.power.user_max_power) / 100.0
        direction_vector *= np.float32(scale)

    def _scale_regulator_direction_vector(self, regulator_direction_vector: NDArray[np.float32]) -> None:
        power = float(self.state.rov_config.power.regulator_max_power) / 100.0
        _ = np.clip(regulator_direction_vector, -power, power, out=regulator_direction_vector)

    # -------------------------------------------------------------------------
    # Public API (must keep name/signature): apply_regulator_to_direction_vector
    # -------------------------------------------------------------------------
    def apply_regulator_to_direction_vector(self, direction_vector: NDArray[np.float32]) -> None:
        """Apply regulator actuation to direction vector in-place."""
        regulator_direction_vector = np.zeros(8, dtype=np.float32)

        depth_hold = bool(self.state.system_status.depth_hold)
        pitch_stab = bool(self.state.system_status.pitch_stabilization)
        roll_stab = bool(self.state.system_status.roll_stabilization)
        yaw_stab = bool(self._yaw_stab_enabled())

        if depth_hold and not self._prev_depth_hold:
            self._depth_hold_enable_edge()
        if (pitch_stab or roll_stab or yaw_stab) and not (self._prev_pitch_stab or self._prev_roll_stab or self._prev_yaw_stab):
            self._attitude_enable_edge()

        self._prev_depth_hold = depth_hold
        self._prev_pitch_stab = pitch_stab
        self._prev_roll_stab = roll_stab
        self._prev_yaw_stab = yaw_stab

        heave_input = float(direction_vector[2])
        self._handle_depth_hold_setpoint(heave_input)

        heave_cmd = self._handle_depth_hold(heave_input)
        if depth_hold:
            dir_coeffs = self.state.rov_config.direction_coefficients
            surge_coeff = float(getattr(dir_coeffs, "surge", 1.0)) or 1.0
            sway_coeff = float(getattr(dir_coeffs, "sway", 1.0)) or 1.0
            heave_coeff = float(getattr(dir_coeffs, "heave", 1.0)) or 1.0

            world_vel = np.array([0.0, 0.0, heave_coeff * float(heave_cmd)], dtype=np.float64)
            u_body = self._solve_body_vector_from_world(
                world_vel,
                np.array([surge_coeff, sway_coeff, heave_coeff], dtype=np.float64),
            )
            regulator_direction_vector[0:3] = u_body

        regulator_direction_vector[3] = np.float32(self._handle_pitch_stabilization(float(direction_vector[3])))
        regulator_direction_vector[5] = np.float32(self._handle_roll_stabilization(float(direction_vector[5])))
        regulator_direction_vector[4] = np.float32(self._handle_yaw_stabilization(float(direction_vector[4])))

        self._scale_regulator_direction_vector(regulator_direction_vector)

        if depth_hold:
            self._transform_translation_for_depth_hold(direction_vector)

        self._scale_direction_vector_with_user_max_power(direction_vector)

        if pitch_stab:
            direction_vector[3] = 0.0
        if roll_stab:
            direction_vector[5] = 0.0
        if yaw_stab:
            direction_vector[4] = 0.0

        direction_vector += regulator_direction_vector

        if pitch_stab or roll_stab or yaw_stab:
            self._transform_world_orientation_to_body(direction_vector)


    def handle_auto_tuning(self, current_time: float) -> NDArray[np.float32] | None:
        """Handle auto-tuning process for PID parameters."""
        if not self.auto_tuning_phase:
            self.auto_tuning_phase = "pitch"
            self.auto_tuning_step = "find_zero"
            self.auto_tuning_data = []
            self.auto_tuning_params = {}
            self.auto_tuning_last_update = current_time
            self.auto_tuning_zero_actuation = 0.0
            self.auto_tuning_amplitude = 0.0
            self.auto_tuning_oscillation_start = 0.0
            log_info("Starting regulator auto tuning")

        dt = current_time - self.auto_tuning_last_update
        if dt < 1 / 60:
            return np.zeros(8, dtype=np.float32)

        self.auto_tuning_last_update = current_time

        if self.auto_tuning_phase == "pitch":
            return self._handle_pitch_tuning(current_time)
        elif self.auto_tuning_phase == "roll":
            return self._handle_roll_tuning(current_time)
        elif self.auto_tuning_phase == "depth":
            return self._handle_depth_tuning(current_time)
        else:
            self.state.regulator.auto_tuning_active = False
            toast_success(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Auto tuning completed",
                description="PID parameters updated",
                cancel=None,
            )
            log_info("Regulator auto tuning completed")
            suggestions = RegulatorSuggestions(
                payload=RegulatorSuggestionsPayload(
                    pitch=self.auto_tuning_params.get(
                        "pitch", RegulatorPID(kp=0, ki=0, kd=0)
                    ),
                    roll=self.auto_tuning_params.get(
                        "roll", RegulatorPID(kp=0, ki=0, kd=0)
                    ),
                    depth=self.auto_tuning_params.get(
                        "depth", RegulatorPID(kp=0, ki=0, kd=0)
                    ),
                )
            )
            queue = get_message_queue()
            queue.put_nowait(suggestions)

    def _handle_pitch_tuning(self, current_time: float) -> NDArray[np.float32]:
        pitch = self.state.regulator.pitch

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning pitch",
                description="Finding zero point...",
                cancel=None,
            )
            if abs(pitch) < AUTO_TUNING_ZERO_THRESHOLD_DEGREES:
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Pitch zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += 0.001 if pitch > 0 else -0.001
                return np.array(
                    [0, 0, 0, self.auto_tuning_zero_actuation, 0, 0, 0, 0],
                    dtype=np.float32,
                )

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning pitch",
                description="Finding oscillation amplitude...",
                cancel=None,
            )
            self.auto_tuning_amplitude += 0.002
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if pitch > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            if abs(pitch) > AUTO_TUNING_AMPLITUDE_THRESHOLD_DEGREES:
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Pitch amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, 0, actuation, 0, 0, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= AUTO_TUNING_OSCILLATION_DURATION_SECONDS:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("pitch")
                return np.zeros(8, dtype=np.float32)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if pitch > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            self.auto_tuning_data.append((current_time, pitch))
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning pitch",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, 0, actuation, 0, 0, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "roll"
            self.auto_tuning_step = "find_zero"
            self.auto_tuning_data = []
            self.auto_tuning_zero_actuation = 0.0
            self.auto_tuning_amplitude = 0.0
            log_info("Pitch tuning complete, starting roll")
        return np.zeros(8, dtype=np.float32)

    def _handle_roll_tuning(self, current_time: float) -> NDArray[np.float32]:
        roll = self.state.regulator.roll
        pitch = self.state.regulator.pitch

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning roll",
                description="Finding zero point...",
                cancel=None,
            )
            if abs(roll) < AUTO_TUNING_ZERO_THRESHOLD_DEGREES:
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Roll zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += 0.001 if roll > 0 else -0.001
                pitch_comp = -pitch * self.state.rov_config.regulator.pitch.kp * 0.5
                return np.array(
                    [0, 0, 0, pitch_comp, 0, self.auto_tuning_zero_actuation, 0, 0],
                    dtype=np.float32,
                )

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning roll",
                description="Finding oscillation amplitude...",
                cancel=None,
            )
            self.auto_tuning_amplitude += 0.002
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if roll > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            pitch_comp = -pitch * self.state.rov_config.regulator.pitch.kp * 0.5
            if abs(roll) > AUTO_TUNING_AMPLITUDE_THRESHOLD_DEGREES:
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Roll amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, 0, pitch_comp, 0, actuation, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= AUTO_TUNING_OSCILLATION_DURATION_SECONDS:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("roll")
                return np.zeros(8, dtype=np.float32)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if roll > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            pitch_comp = -pitch * self.state.rov_config.regulator.pitch.kp * 0.5
            self.auto_tuning_data.append((current_time, roll))
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning roll",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, 0, pitch_comp, 0, actuation, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "depth"
            self.auto_tuning_step = "find_zero"
            self.auto_tuning_data = []
            self.auto_tuning_zero_actuation = 0.0
            self.auto_tuning_amplitude = 0.0
            log_info("Roll tuning complete, starting depth")
            return np.zeros(8, dtype=np.float32)

        return np.zeros(8, dtype=np.float32)

    def _handle_depth_tuning(self, current_time: float) -> NDArray[np.float32]:
        depth = self.state.pressure.depth

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning depth",
                description="Finding zero point...",
                cancel=None,
            )
            if (
                abs(depth - self.state.regulator.desired_depth)
                < AUTO_TUNING_ZERO_THRESHOLD_DEPTH_METERS
            ):
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Depth zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += (
                    0.001 if depth > self.state.regulator.desired_depth else -0.001
                )
                return np.array(
                    [0, 0, self.auto_tuning_zero_actuation, 0, 0, 0, 0, 0],
                    dtype=np.float32,
                )

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning depth",
                description="Finding oscillation amplitude...",
                cancel=None,
            )
            self.auto_tuning_amplitude += 0.002
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if depth > self.state.regulator.desired_depth
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            if (
                abs(depth - self.state.regulator.desired_depth)
                > AUTO_TUNING_AMPLITUDE_THRESHOLD_DEPTH_METERS
            ):
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Depth amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, actuation, 0, 0, 0, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= AUTO_TUNING_OSCILLATION_DURATION_SECONDS:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("depth")
                return np.zeros(8, dtype=np.float32)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if depth > self.state.regulator.desired_depth
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            self.auto_tuning_data.append((current_time, depth))
            toast_loading(
                toast_id=AUTO_TUNING_TOAST_ID,
                message="Tuning depth",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, actuation, 0, 0, 0, 0, 0], dtype=np.float32)

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "done"
            log_info("Depth tuning complete")
            return np.zeros(8, dtype=np.float32)

        return np.zeros(8, dtype=np.float32)

    def _fit_curve(self, axis: str) -> None:
        if not self.auto_tuning_data:
            log_error(f"No data for {axis} curve fitting")
            return

        times = [t[0] for t in self.auto_tuning_data]
        values = [t[1] for t in self.auto_tuning_data]
        times = np.array(times, dtype=np.float32) - times[0]
        values = np.array(values, dtype=np.float32)

        def sine_wave(
            x: NDArray[np.float32], a: float, f: float, phi: float, offset: float
        ) -> NDArray[np.float32]:
            return cast(
                NDArray[np.float32], a * np.sin(2 * np.pi * f * x + phi) + offset
            )

        try:
            params, _ = curve_fit(
                sine_wave,
                times,
                values,
                p0=[(np.max(values) - np.min(values)) / 2, 1 / 10, 0, np.mean(values)],
            )
            a, f, _, _ = params
            a = cast(np.float32, a)
            f = cast(np.float32, f)
            tu = 1 / f
            ku = (4 * self.auto_tuning_amplitude) / (np.pi * a)
            kp = float(0.6 * ku)
            ki = float(1.2 * ku / tu)
            kd = float(0.075 * ku * tu)
            self.auto_tuning_params[axis] = RegulatorPID(kp=kp, ki=ki, kd=kd)
            log_info(f"{axis} PID: Kp={kp:.3f}, Ki={ki:.3f}, Kd={kd:.3f}")
        except Exception as e:
            log_error(f"Curve fitting failed for {axis}: {e}")
            self.auto_tuning_params[axis] = RegulatorPID(kp=0, ki=0, kd=0)
