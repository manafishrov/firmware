"""Regulator module for ROV control (NED convention)."""

import time
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import curve_fit
from scipy.spatial.transform import Rotation

from .constants import (
    AHRS_ACCEL_MIN_NORM,
    AHRS_MAHONY_KI,
    AHRS_MAHONY_KP,
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEGREES,
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEPTH_METERS,
    AUTO_TUNING_OSCILLATION_DURATION_SECONDS,
    AUTO_TUNING_TOAST_ID,
    AUTO_TUNING_ZERO_THRESHOLD_DEGREES,
    AUTO_TUNING_ZERO_THRESHOLD_DEPTH_METERS,
    DEPTH_DERIVATIVE_EMA_TAU,
    DEPTH_INTEGRAL_WINDUP_CLIP,
    INTEGRAL_RELAX_THRESHOLD,
    INTEGRAL_WINDUP_CLIP_DEGREES,
    MAX_GYRO_DEG_PER_SEC,
    PITCH_MAX,
    THRUSTER_SEND_FREQUENCY,
)
from .log import log_error, log_info
from .models.config import (
    AxisConfig,
    RegulatorSuggestions as RegulatorSuggestionsPayload,
)
from .rov_state import RovState
from .toast import toast_loading, toast_success
from .websocket.message import RegulatorSuggestions
from .websocket.queue import get_message_queue


def _clamp_dt(dt: float) -> float:
    """Clamp a time step to a safe range around the thruster send interval.

    Non-finite dt values are replaced with 1/THRUSTER_SEND_FREQUENCY. Finite dt values are constrained to the interval
    [0.5 * (1/THRUSTER_SEND_FREQUENCY), 10 * (1/THRUSTER_SEND_FREQUENCY)].

    Parameters:
        dt (float): Proposed time delta in seconds.

    Returns:
        float: Clamped time delta in seconds.
    """
    if not np.isfinite(dt):
        return 1 / THRUSTER_SEND_FREQUENCY
    return cast(
        float,
        np.clip(
            dt,
            (1 / THRUSTER_SEND_FREQUENCY) * 0.5,
            (1 / THRUSTER_SEND_FREQUENCY) * 10,
            dtype=np.float32,
        ),
    )


class _MahonyAhrs:
    """Mahony AHRS (gyro + accel) in quaternion form.

    - Stabilizes roll/pitch with accel (gravity).
    - Yaw is integrated from gyro (will drift without external heading reference).
    """

    def __init__(self, kp: float, ki: float) -> None:
        """Create a Mahony AHRS estimator configured with the given proportional and integral gains.

        Parameters:
            kp (float): Proportional gain for the attitude correction term.
            ki (float): Integral gain for error accumulation over time.

        Notes:
            Initializes the internal integral term to a zero 3-vector and sets the current attitude to identity (no rotation).
        """
        self.kp: float = float(kp)
        self.ki: float = float(ki)
        self._integral: NDArray[np.float32] = np.zeros(3, dtype=np.float32)
        self.current_attitude: Rotation = Rotation.identity()

    def reset(self) -> None:
        """Reset the AHRS internal state to its initial condition.

        Sets the integral error accumulator to zero and the estimated attitude to the identity rotation (no rotation).
        """
        self._integral[:] = 0.0
        self.current_attitude = Rotation.identity()

    def update(
        self,
        gyro_rad_s: NDArray[np.float32],
        accel: NDArray[np.float32],
        dt: float,
    ) -> None:
        """Update internal attitude estimate from gyroscope and accelerometer readings.

        Clamps the provided time step, rejects unreasonably large gyro samples (zeroing them),
        and uses the Mahony AHRS update: when accelerometer data is valid the method applies
        proportional and integral corrections based on the measured gravity direction; if the
        accelerometer norm is invalid or too small it falls back to gyro-only integration.
        The method updates the filter's internal attitude and integral state.

        Parameters:
            gyro_rad_s (NDArray[np.float32]): Gyroscope rates in radians per second (3-element array).
            accel (NDArray[np.float32]): Accelerometer vector in m/s^2 (3-element array).
            dt (float): Elapsed time since last update in seconds (will be clamped to a safe range).
        """
        dt = _clamp_dt(dt)

        # Discard gyro reading if unreasonable big
        if np.any(
            cast(NDArray[np.float32], np.abs(gyro_rad_s, dtype=np.float32))
            > cast(np.float32, np.deg2rad(MAX_GYRO_DEG_PER_SEC, dtype=np.float32))
        ):
            log_error("AHRS: Discarding unreasonable gyro reading")
            gyro_rad_s[:] = 0.0

        ax, ay, az = cast(float, accel[0]), cast(float, accel[1]), cast(float, accel[2])
        a_norm = cast(float, np.sqrt(ax * ax + ay * ay + az * az))
        if not np.isfinite(a_norm) or a_norm < AHRS_ACCEL_MIN_NORM:
            self._integrate_gyro_only(gyro_rad_s, dt)
            return

        a = cast(
            NDArray[np.float32], np.array([ax, ay, az], dtype=np.float32) / a_norm
        )  # Normalized accel measurement

        # Estimated "up" direction in body frame from current attitude (the reason we use up is that this is the expected accel from gravity).
        g_body = cast(
            NDArray[np.float32],
            self.current_attitude.inv().apply(
                np.array([0.0, 0.0, -1.0], dtype=np.float32)
            ),
        )

        # Error drives estimated up toward measured accel direction.
        e = cast(NDArray[np.float32], np.cross(a, g_body))

        if self.ki > 0.0:
            self._integral += e * (self.ki * dt)

        omega = np.array(
            [
                gyro_rad_s[0] + self.kp * e[0] + self._integral[0],
                gyro_rad_s[1] + self.kp * e[1] + self._integral[1],
                gyro_rad_s[2] + self.kp * e[2] + self._integral[2],
            ],
            dtype=np.float32,
        )

        self._integrate_omega(omega, dt)

    def _integrate_gyro_only(self, gyro_rad_s: NDArray[np.float32], dt: float) -> None:
        """Advance the internal attitude estimate by integrating gyro angular rates only.

        Parameters:
            gyro_rad_s (NDArray[np.float32]): Angular velocity vector [rad/s] in body frame (gx, gy, gz).
            dt (float): Time step in seconds over which to integrate.
        """
        omega = np.array(
            [gyro_rad_s[0], gyro_rad_s[1], gyro_rad_s[2]],
            dtype=np.float32,
        )
        self._integrate_omega(omega, dt)

    def _integrate_omega(self, omega_rad_s: NDArray[np.float32], dt: float) -> None:
        """Integrates an angular velocity vector over a time step and updates the current attitude quaternion.

        Parameters:
            omega_rad_s (NDArray[np.float32]): Angular velocity vector in radians per second (rotation vector in body frame).
            dt (float): Time step in seconds.

        Details:
            - Applies the rotation represented by omega_rad_s * dt to self.current_attitude.
            - Normalizes the resulting quaternion to unit length and stores it back to self.current_attitude.
        """
        dtheta = omega_rad_s * dt
        dr = Rotation.from_rotvec(dtheta)
        self.current_attitude = self.current_attitude * dr  # body-to-world update

        q = cast(NDArray[np.float32], self.current_attitude.as_quat())
        q /= np.linalg.norm(q)
        self.current_attitude = Rotation.from_quat(q)


class Regulator:
    """PID regulator for ROV stabilization."""

    def __init__(self, state: RovState):
        """Initialize the Regulator with ROV state.

        Args:
            state: The RovState object containing the current ROV state and configuration.
        """
        self.state: RovState = state

        self.gyro_rad_s: NDArray[np.float32] = np.array(
            [0.0, 0.0, 0.0], dtype=np.float32
        )  # rad/s

        self.last_update_ahrs_time: float = 0.0
        self.delta_t_update_ahrs: float = 1 / THRUSTER_SEND_FREQUENCY
        self.last_run_regulator_time: float = 0.0
        self.delta_t_run_regulator: float = 1 / THRUSTER_SEND_FREQUENCY

        self.previous_depth: float = 0.0
        self.current_dt_depth: float = 0.0

        # Quaternion attitude estimator
        self.ahrs: _MahonyAhrs = _MahonyAhrs(kp=AHRS_MAHONY_KP, ki=AHRS_MAHONY_KI)

        self.desired_attitude: Rotation = Rotation.identity()
        self.integral_attitude_rad: NDArray[np.float32] = np.array(
            [0.0, 0.0, 0.0], dtype=np.float32
        )
        self.integral_depth: float = 0.0

        # Edge detection for resetting when enabling regulators
        self._prev_depth_hold_enabled: bool = False
        self._prev_stabilization_enabled: bool = False

        self.auto_tuning_phase: str = ""
        self.auto_tuning_step: str = ""
        self.auto_tuning_data: list[tuple[float, float]] = []
        self.auto_tuning_params: dict[str, AxisConfig] = {}
        self.auto_tuning_last_update: float = 0.0
        self.auto_tuning_zero_actuation: float = 0.0
        self.auto_tuning_amplitude: float = 0.0
        self.auto_tuning_oscillation_start: float = 0.0

    def _update_desired_from_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Update desired depth and attitude targets from the user direction vector.

        When depth hold is enabled, adjusts state.regulator.desired_depth by the heave input
        (direction_vector[2]) scaled by the configured depth_rate and the regulator
        delta-time. When pitch stabilization is enabled, applies yaw, pitch, and roll increments
        (from direction_vector[4], [3], [5] respectively) to self.desired_attitude using
        quaternion operations, clamps pitch to ±PITCH_MAX to avoid gimbal issues, and writes
        desired pitch and roll into state.regulator for UI visualization.

        Parameters:
            direction_vector (ndarray[np.float32]): 8-element NED direction vector where
                index 2 = heave, 3 = pitch input, 4 = yaw input, 5 = roll input.

        """
        if self.state.system_status.depth_hold:
            heave_change = cast(float, direction_vector[2])
            desired_depth = (
                self.state.regulator.desired_depth
                + heave_change
                * self.state.rov_config.regulator.depth.rate
                * self.delta_t_run_regulator
            )
            self.state.regulator.desired_depth = desired_depth

        if self.state.system_status.auto_stabilization:
            desired_yaw_change = cast(
                float,
                direction_vector[4]
                * self.delta_t_run_regulator
                * self.state.rov_config.regulator.yaw.rate,
            )
            yaw_rotation = Rotation.from_rotvec(
                [0.0, 0.0, np.deg2rad(desired_yaw_change, dtype=np.float32)]
            )
            self.desired_attitude = yaw_rotation * self.desired_attitude

            desired_pitch_change = cast(
                float,
                direction_vector[3]
                * self.delta_t_run_regulator
                * self.state.rov_config.regulator.pitch.rate,
            )
            yaw, pitch, roll = cast(
                tuple[float, float, float],
                self.desired_attitude.as_euler("ZYX", degrees=True),
            )
            pitch = pitch + desired_pitch_change
            pitch = cast(float, np.clip(pitch, -PITCH_MAX, PITCH_MAX, dtype=np.float32))
            self.desired_attitude = Rotation.from_euler(
                "ZYX", [yaw, pitch, roll], degrees=True
            )

            desired_roll_change = cast(
                float,
                direction_vector[5]
                * self.delta_t_run_regulator
                * self.state.rov_config.regulator.roll.rate,
            )
            roll_rotation = Rotation.from_rotvec(
                [np.deg2rad(desired_roll_change, dtype=np.float32), 0.0, 0.0]
            )
            self.desired_attitude = self.desired_attitude * roll_rotation

            yaw, pitch, roll = self.desired_attitude.as_euler("ZYX", degrees=True)
            self.state.regulator.desired_pitch = pitch
            self.state.regulator.desired_roll = roll
            self.state.regulator.desired_yaw = yaw

    def update_regulator_data_from_imu(self) -> None:
        """Update internal AHRS and regulator fields from the IMU and write current attitude to state for visualization.

        Updates internal gyro rates used by the regulator, advances the Mahony AHRS using the IMU accelerometer and gyroscope with a clamped delta time, records timing used for future AHRS updates, and writes the estimated pitch and roll into state.regulator for UI/visualization.
        """
        if not self.state.system_health.imu_healthy:
            return

        imu_data = self.state.imu
        accel = np.array(
            cast(np.ndarray, imu_data.acceleration), dtype=np.float32, copy=True
        )
        gyr = np.array(
            cast(np.ndarray, imu_data.gyroscope), dtype=np.float32, copy=True
        )

        self.gyro_rad_s = gyr

        now = time.time()
        if self.last_update_ahrs_time > 0.0:
            self.delta_t_update_ahrs = _clamp_dt(now - self.last_update_ahrs_time)
        else:
            self.delta_t_update_ahrs = 1 / THRUSTER_SEND_FREQUENCY
        self.last_update_ahrs_time = now

        self.ahrs.update(gyr, accel, self.delta_t_update_ahrs)

        yaw, pitch, roll = self.ahrs.current_attitude.as_euler("ZYX", degrees=True)

        self.state.regulator.pitch = pitch
        self.state.regulator.roll = roll
        self.state.regulator.yaw = yaw

    def _handle_edges(self) -> None:
        """Detect and handle rising-edge transitions for depth-hold and stabilization enable flags.

        Checks the regulator-related enable flags in state.system_status and, when either
        feature transitions from disabled to enabled, invokes the corresponding enable
        handler (depth hold or attitude/stabilization). Updates internal previous-state
        flags to reflect the current enablement.
        """
        depth_hold_enabled = self.state.system_status.depth_hold
        stabilization_enabled = self.state.system_status.auto_stabilization

        if depth_hold_enabled and not self._prev_depth_hold_enabled:
            self._depth_hold_enable_edge()
        if stabilization_enabled and not self._prev_stabilization_enabled:
            self._attitude_enable_edge()

        self._prev_depth_hold_enabled = depth_hold_enabled
        self._prev_stabilization_enabled = stabilization_enabled

    def _depth_hold_enable_edge(
        self,
    ) -> None:  # Note to Michael: I know this is done in another script too, but it is better to do here because we have to change the integral terms which are only in this class, and in future we might need to have more complex behaviour on edges.
        """Initialize depth-hold targets and reset related integral/derivative state when depth-hold is enabled.

        Sets the regulator's desired depth to the current measured depth, clears the depth integral term, resets the depth derivative accumulator, and stores the current depth as the previous depth for subsequent derivative calculations.
        """
        current_depth = self.state.pressure.depth
        self.state.regulator.desired_depth = current_depth
        self.integral_depth = 0.0
        self.current_dt_depth = 0.0
        self.previous_depth = current_depth

    def _handle_depth_hold(self, heave_input: np.float32) -> float:
        """Compute PID depth actuation using current and desired depth, with integral relaxation based on user heave input.

        Parameters:
            heave_input (float): User heave command magnitude (typically in [-1, 1]); larger |heave_input| reduces integral accumulation.

        Returns:
            float: Depth regulator actuation; positive values command upward (reduce depth), negative values command downward.
        """
        current_depth = self.state.pressure.depth
        desired_depth = self.state.regulator.desired_depth

        error = desired_depth - current_depth

        integral_scale = cast(
            np.float32,
            np.clip((1.0 - abs(heave_input)), 0.0, 1.0, dtype=np.float32),
        )
        self.integral_depth += float(
            error * self.delta_t_run_regulator * integral_scale
        )

        self.integral_depth = np.clip(
            self.integral_depth,
            -DEPTH_INTEGRAL_WINDUP_CLIP,
            DEPTH_INTEGRAL_WINDUP_CLIP,
            dtype=np.float32,
        )

        # Update derivative term (using EMA filter)
        alpha = cast(
            float, np.exp(-self.delta_t_run_regulator / DEPTH_DERIVATIVE_EMA_TAU)
        )
        raw_rate = (current_depth - self.previous_depth) / self.delta_t_run_regulator
        self.current_dt_depth = alpha * self.current_dt_depth + (1.0 - alpha) * raw_rate
        self.previous_depth = current_depth

        config = self.state.rov_config.regulator
        depth_regulator_actuation = (
            float(config.depth.kp) * error
            + float(config.depth.ki) * float(self.integral_depth)
            + float(config.depth.kd) * float(self.current_dt_depth)
        )

        return depth_regulator_actuation

    def _attitude_enable_edge(self) -> None:
        """Set the target attitude to level (zero pitch and roll) while preserving the current yaw, and reset the attitude integral term.

        This updates `desired_attitude` so pitch and roll are zero and the yaw equals the AHRS's current yaw, then clears `integral_attitude_rad`.
        """
        self.desired_attitude = Rotation.identity()
        current_yaw = self.ahrs.current_attitude.as_euler("ZYX", degrees=False)[0]
        yaw_rotation = Rotation.from_rotvec([0.0, 0.0, current_yaw])
        self.desired_attitude = yaw_rotation * self.desired_attitude

        self.integral_attitude_rad[:] = 0.0

    def _handle_stabilization(
        self, direction_vector_attitude: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Compute a quaternion-based PID stabilization actuation for attitude.

        Parameters:
            direction_vector_attitude (ndarray): 3-element array of user attitude inputs (pitch, yaw, roll) in body frame; when its magnitude is above the integral-relax threshold the attitude integral term is not accumulated.

        Returns:
            ndarray: 3-element float32 array [pitch_actuation, yaw_actuation, roll_actuation] containing the PID actuation for each attitude axis (already scaled down for safe application).
        """
        dt = self.delta_t_run_regulator
        config = self.state.rov_config.regulator

        current_attitude: Rotation = self.ahrs.current_attitude
        desired_attitude: Rotation = self.desired_attitude

        r_err = current_attitude.inv() * desired_attitude

        err_rotvec = cast(NDArray[np.float32], r_err.as_rotvec().astype(np.float32))
        if not np.all(np.isfinite(err_rotvec)):
            err_rotvec = np.zeros(3, dtype=np.float32)

        if np.linalg.norm(direction_vector_attitude[0:3]) < INTEGRAL_RELAX_THRESHOLD:
            self.integral_attitude_rad += err_rotvec * dt

        clip_rad = cast(
            np.float32, np.deg2rad(INTEGRAL_WINDUP_CLIP_DEGREES, dtype=np.float32)
        )
        self.integral_attitude_rad = np.clip(
            self.integral_attitude_rad, -clip_rad, clip_rad, dtype=np.float32
        )

        omega = self.gyro_rad_s.astype(np.float32, copy=False)

        # PID per axis (roll=x, pitch=y, yaw=z)
        u_roll = cast(
            float,
            config.roll.kp * err_rotvec[0]
            + config.roll.ki * self.integral_attitude_rad[0]
            + config.roll.kd * (-omega[0]),
        )
        u_pitch = cast(
            float,
            config.pitch.kp * err_rotvec[1]
            + config.pitch.ki * self.integral_attitude_rad[1]
            + config.pitch.kd * (-omega[1]),
        )
        u_yaw = cast(
            float,
            config.yaw.kp * err_rotvec[2]
            + config.yaw.ki * self.integral_attitude_rad[2]
            + config.yaw.kd * (-omega[2]),
        )

        stabilization_actuation = (
            np.array([u_pitch, u_yaw, u_roll], dtype=np.float32) / 10.0
        )

        return stabilization_actuation

    def _transform_movement_vector_world_to_body(
        self, direction_vector_movement: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Convert a world-frame surge/sway/heave movement vector into the vehicle body frame and apply per-axis direction coefficients.

        Parameters:
            direction_vector_movement (NDArray[np.float32]): 3-element world-frame movement vector [surge, sway, heave].

        Returns:
            NDArray[np.float32]: 3-element movement vector expressed in the body frame with direction coefficients applied.
        """
        surge_movement_world = np.array(
            [direction_vector_movement[0], 0, 0], dtype=np.float32
        )
        sway_movement_world = np.array(
            [0, direction_vector_movement[1], 0], dtype=np.float32
        )
        heave_movement_world = np.array(
            [0, 0, direction_vector_movement[2]], dtype=np.float32
        )

        current_attitude = self.ahrs.current_attitude

        # Remove yaw component from current attitude, because surge should always make ROV move forward relative to body, regardless of yaw
        _yaw, pitch, roll = current_attitude.as_euler("ZYX", degrees=False)
        current_attitude = Rotation.from_euler("ZYX", [0, pitch, roll], degrees=False)

        surge_movement_body = current_attitude.inv().apply(surge_movement_world)
        sway_movement_body = current_attitude.inv().apply(sway_movement_world)
        heave_movement_body = current_attitude.inv().apply(heave_movement_world)

        dir_coeffs = self.state.rov_config.direction_coefficients
        surge_coeff = dir_coeffs.surge if np.isfinite(dir_coeffs.surge) else 1.0
        sway_coeff = dir_coeffs.sway if np.isfinite(dir_coeffs.sway) else 1.0
        heave_coeff = dir_coeffs.heave if np.isfinite(dir_coeffs.heave) else 1.0

        surge_heave_ratio = surge_coeff / heave_coeff if heave_coeff != 0 else 0.0
        sway_heave_ratio = sway_coeff / heave_coeff if heave_coeff != 0 else 0.0
        heave_surge_ratio = heave_coeff / surge_coeff if surge_coeff != 0 else 0.0
        heave_sway_ratio = heave_coeff / sway_coeff if sway_coeff != 0 else 0.0

        surge_movement_body *= np.array([1.0, 1.0, surge_heave_ratio], dtype=np.float32)
        sway_movement_body *= np.array([1.0, 1.0, sway_heave_ratio], dtype=np.float32)
        heave_movement_body *= np.array(
            [heave_surge_ratio, heave_sway_ratio, 1.0], dtype=np.float32
        )

        world_frame_movement = (
            surge_movement_body + sway_movement_body + heave_movement_body
        )

        return world_frame_movement.astype(np.float32, copy=False)

    def _scale_direction_vector_with_user_max_power(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Apply the user-configured maximum power percentage to the provided direction vector in place.

        Scales the given NumPy float32 direction_vector by state.rov_config.power.user_max_power / 100.0 and updates the array directly.

        Parameters:
            direction_vector (numpy.ndarray): Mutable 1-D float32 array (expected length 8) representing the direction vector to be scaled in place.
        """
        scale = float(self.state.rov_config.power.user_max_power) / 100.0
        direction_vector *= np.float32(scale)

    def _scale_regulator_direction_vector(
        self, regulator_direction_vector: NDArray[np.float32]
    ) -> None:
        """Clip the regulator direction vector in-place to the configured per-axis maximum regulator power.

        Parameters:
            regulator_direction_vector (NDArray[np.float32]): Array of regulator outputs (modified in-place). Each element is clamped to the range [-p, p], where p = state.rov_config.power.regulator_max_power / 100.0.
        """
        power = float(self.state.rov_config.power.regulator_max_power) / 100.0
        _ = np.clip(
            regulator_direction_vector,
            -power,
            power,
            out=regulator_direction_vector,
            dtype=np.float32,
        )

    def apply_regulator_to_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Apply active regulator outputs to the provided 8-element direction vector in place.

        This updates internal timing, refreshes regulator targets from user input and edge transitions, computes depth-hold and attitude-stabilization contributions when enabled, scales both user and regulator components according to configuration, and adds the regulator vector into the provided direction_vector.

        Parameters:
            direction_vector (NDArray[np.float32]): Mutable 8-element NED-format command vector arranged as
                [surge, sway, heave, pitch, yaw, roll, action1, action2]. The array is modified in place:
                - depth hold replaces heave (index 2) with regulator-modified motion and zeroes user heave,
                - attitude stabilization zeroes user pitch/yaw/roll (indices 3:6) and adds regulator corrections,
                - final result is the elementwise sum of the (possibly scaled) user vector and the scaled regulator contributions.
        """
        regulator_direction_vector = np.zeros(8, dtype=np.float32)

        now = time.time()
        if self.last_run_regulator_time > 0.0:
            self.delta_t_run_regulator = _clamp_dt(now - self.last_run_regulator_time)
        else:
            self.delta_t_run_regulator = 1 / THRUSTER_SEND_FREQUENCY
        self.last_run_regulator_time = now

        self._update_desired_from_direction_vector(direction_vector)
        self._handle_edges()

        if self.state.system_status.depth_hold:
            depth_regulator_actuation = self._handle_depth_hold(
                cast(np.float32, direction_vector[2])
            )
            regulator_direction_vector[0:3] = (
                self._transform_movement_vector_world_to_body(
                    np.array([0.0, 0.0, depth_regulator_actuation], dtype=np.float32)
                )
            )
            direction_vector[2] = 0.0
            direction_vector[0:3] = self._transform_movement_vector_world_to_body(
                direction_vector[0:3].copy()
            )

        if self.state.system_status.auto_stabilization:
            regulator_direction_vector[3:6] = self._handle_stabilization(
                direction_vector[3:6].copy()
            )
            direction_vector[3:6] = 0.0

        self._scale_regulator_direction_vector(regulator_direction_vector)
        self._scale_direction_vector_with_user_max_power(direction_vector)

        direction_vector += regulator_direction_vector

    def handle_auto_tuning(self, current_time: float) -> NDArray[np.float32] | None:
        """Progresses the regulator auto-tuning state machine and produces the actuation vector to apply for the current tuning step.

        This updates internal auto-tuning state (phase, step, collected data, timers) and, when tuning completes, sets `state.regulator.auto_tuning_active` to False and publishes tuned PID suggestions via the message queue. If called with intervals smaller than 1/60 s, returns a zeroed 8-element actuation vector without advancing the state.

        Returns:
            An 8-element numpy float32 array containing the actuation to apply for the current tuning step, or `None` when auto-tuning has finished and results have been published.
        """
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
                        "pitch", AxisConfig(kp=0, ki=0, kd=0)
                    ),
                    roll=self.auto_tuning_params.get(
                        "roll", AxisConfig(kp=0, ki=0, kd=0)
                    ),
                    depth=self.auto_tuning_params.get(
                        "depth", AxisConfig(kp=0, ki=0, kd=0)
                    ),
                    yaw=self.auto_tuning_params.get(
                        "depth", AxisConfig(kp=0, ki=0, kd=0)
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
        times = np.array(times, dtype=np.float32) - np.float32(times[0])
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
            self.auto_tuning_params[axis] = AxisConfig(kp=kp, ki=ki, kd=kd)
            log_info(f"{axis} PID: Kp={kp:.3f}, Ki={ki:.3f}, Kd={kd:.3f}")
        except Exception as e:
            log_error(f"Curve fitting failed for {axis}: {e}")
            self.auto_tuning_params[axis] = AxisConfig(kp=0, ki=0, kd=0)
