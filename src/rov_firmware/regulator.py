"""Regulator module for ROV control (NED convention)."""

import asyncio
import math
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
from .models.toast import ToastVariant
from .rov_state import RovState
from .toast import ToastContent, toast_content
from .websocket.message import RegulatorSuggestions
from .websocket.queue import get_message_queue


# Subscripting NDArray re-runs the typing machinery on every evaluation, which
# costs ~8 us per call site. Bind it once so hot-path casts stay free.
_F32 = NDArray[np.float32]

_NOMINAL_DT = 1 / THRUSTER_SEND_FREQUENCY
_MIN_DT = _NOMINAL_DT * 0.5
_MAX_DT = _NOMINAL_DT * 10
_MAX_GYRO_RAD_PER_SEC = math.radians(MAX_GYRO_DEG_PER_SEC)
_INTEGRAL_WINDUP_CLIP_RAD = math.radians(INTEGRAL_WINDUP_CLIP_DEGREES)


def _clamp_dt(dt: float) -> float:
    """Clamp a time step to a safe range around the thruster send interval.

    Non-finite dt values are replaced with 1/THRUSTER_SEND_FREQUENCY. Finite dt values are constrained to the interval
    [0.5 * (1/THRUSTER_SEND_FREQUENCY), 10 * (1/THRUSTER_SEND_FREQUENCY)].

    Parameters:
        dt (float): Proposed time delta in seconds.

    Returns:
        float: Clamped time delta in seconds.
    """
    if not math.isfinite(dt):
        return _NOMINAL_DT
    if dt < _MIN_DT:
        return _MIN_DT
    if dt > _MAX_DT:
        return _MAX_DT
    return dt


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
        self._omega_buffer: NDArray[np.float32] = np.zeros(3, dtype=np.float32)
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

        gx, gy, gz = float(gyro_rad_s[0]), float(gyro_rad_s[1]), float(gyro_rad_s[2])

        # Discard gyro reading if unreasonable big
        if max(abs(gx), abs(gy), abs(gz)) > _MAX_GYRO_RAD_PER_SEC:
            log_error("AHRS: Discarding unreasonable gyro reading")
            gyro_rad_s[:] = 0.0
            gx = gy = gz = 0.0

        ax, ay, az = float(accel[0]), float(accel[1]), float(accel[2])
        a_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if not math.isfinite(a_norm) or a_norm < AHRS_ACCEL_MIN_NORM:
            self._integrate_gyro_only(gyro_rad_s, dt)
            return

        # Normalized accel measurement
        ax /= a_norm
        ay /= a_norm
        az /= a_norm

        # Estimated "up" direction in body frame from current attitude (the reason we use up is that this is the expected accel from gravity).
        # Rotating [0, 0, -1] by the inverse attitude selects the negated third row of the rotation matrix.
        third_row = self.current_attitude.as_matrix()[2]
        bx, by, bz = -float(third_row[0]), -float(third_row[1]), -float(third_row[2])

        # Error drives estimated up toward measured accel direction.
        ex = ay * bz - az * by
        ey = az * bx - ax * bz
        ez = ax * by - ay * bx

        integral = self._integral
        if self.ki > 0.0:
            gain = self.ki * dt
            integral[0] += ex * gain
            integral[1] += ey * gain
            integral[2] += ez * gain

        omega = self._omega_buffer
        omega[0] = gx + self.kp * ex + integral[0]
        omega[1] = gy + self.kp * ey + integral[1]
        omega[2] = gz + self.kp * ez + integral[2]

        self._integrate_omega(omega, dt)

    def _integrate_gyro_only(self, gyro_rad_s: NDArray[np.float32], dt: float) -> None:
        """Advance the internal attitude estimate by integrating gyro angular rates only.

        Parameters:
            gyro_rad_s (NDArray[np.float32]): Angular velocity vector [rad/s] in body frame (gx, gy, gz).
            dt (float): Time step in seconds over which to integrate.
        """
        omega = self._omega_buffer
        omega[:] = gyro_rad_s
        self._integrate_omega(omega, dt)

    def _integrate_omega(self, omega_rad_s: NDArray[np.float32], dt: float) -> None:
        """Integrates an angular velocity vector over a time step and updates the current attitude quaternion.

        Parameters:
            omega_rad_s (NDArray[np.float32]): Angular velocity vector in radians per second (rotation vector in body frame).
            dt (float): Time step in seconds.

        Details:
            - Applies the rotation represented by omega_rad_s * dt to self.current_attitude.
            - Rotation stores unit quaternions internally, so the result stays normalized.
        """
        dtheta = omega_rad_s * dt
        dr = Rotation.from_rotvec(dtheta)
        self.current_attitude = self.current_attitude * dr  # body-to-world update


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
        self._accel_buffer: NDArray[np.float32] = np.zeros(3, dtype=np.float32)
        self._gyro_buffer: NDArray[np.float32] = np.zeros(3, dtype=np.float32)
        self._regulator_direction_vector: NDArray[np.float32] = np.zeros(
            8, dtype=np.float32
        )
        self._unlimited_direction_vector: NDArray[np.float32] = np.zeros(
            8, dtype=np.float32
        )
        self._depth_hold_vector_buffer: NDArray[np.float32] = np.zeros(
            3, dtype=np.float32
        )
        self._movement_vector_buffer: NDArray[np.float32] = np.zeros(
            3, dtype=np.float32
        )
        self._stabilization_input_buffer: NDArray[np.float32] = np.zeros(
            3, dtype=np.float32
        )
        self._stabilization_actuation_buffer: NDArray[np.float32] = np.zeros(
            3, dtype=np.float32
        )
        self._world_frame_movement_buffer: NDArray[np.float32] = np.zeros(
            3, dtype=np.float32
        )

        self.last_update_ahrs_time: float = 0.0
        self.delta_t_update_ahrs: float = _NOMINAL_DT
        self.last_run_regulator_time: float = 0.0
        self.delta_t_run_regulator: float = _NOMINAL_DT

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

        Axes whose increment is exactly zero contribute an identity rotation, so their
        quaternion work is skipped. The pitch clamp still runs every tick because
        fpv_mode leaves the target unclamped.

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
            regulator_config = self.state.rov_config.regulator
            dt = self.delta_t_run_regulator
            desired_yaw_change = (
                float(direction_vector[4]) * dt * regulator_config.yaw.rate
            )
            desired_pitch_change = (
                float(direction_vector[3]) * dt * regulator_config.pitch.rate
            )
            desired_roll_change = (
                float(direction_vector[5]) * dt * regulator_config.roll.rate
            )

            if not regulator_config.fpv_mode:
                if desired_yaw_change != 0.0:
                    yaw_rotation = Rotation.from_rotvec(
                        [0.0, 0.0, math.radians(desired_yaw_change)]
                    )
                    self.desired_attitude = yaw_rotation * self.desired_attitude

                yaw, pitch, roll = cast(
                    tuple[float, float, float],
                    self.desired_attitude.as_euler("ZYX", degrees=True),
                )
                clamped_pitch = pitch + desired_pitch_change
                if clamped_pitch > PITCH_MAX:
                    clamped_pitch = PITCH_MAX
                elif clamped_pitch < -PITCH_MAX:
                    clamped_pitch = -PITCH_MAX
                if clamped_pitch != pitch:
                    self.desired_attitude = Rotation.from_euler(
                        "ZYX", [yaw, clamped_pitch, roll], degrees=True
                    )

                if desired_roll_change != 0.0:
                    roll_rotation = Rotation.from_rotvec(
                        [math.radians(desired_roll_change), 0.0, 0.0]
                    )
                    self.desired_attitude = self.desired_attitude * roll_rotation

            elif (
                desired_yaw_change != 0.0
                or desired_pitch_change != 0.0
                or desired_roll_change != 0.0
            ):
                local_rotation = Rotation.from_rotvec(
                    [
                        math.radians(desired_roll_change),
                        math.radians(desired_pitch_change),
                        math.radians(desired_yaw_change),
                    ]
                )
                self.desired_attitude = self.desired_attitude * local_rotation

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
        accel = self._accel_buffer
        accel[:] = imu_data.acceleration
        gyr = self._gyro_buffer
        gyr[:] = imu_data.gyroscope

        self.gyro_rad_s[:] = gyr

        now = time.time()
        if self.last_update_ahrs_time > 0.0:
            self.delta_t_update_ahrs = _clamp_dt(now - self.last_update_ahrs_time)
        else:
            self.delta_t_update_ahrs = _NOMINAL_DT
        self.last_update_ahrs_time = now

        self.ahrs.update(gyr, accel, self.delta_t_update_ahrs)

        yaw, pitch, roll = self.ahrs.current_attitude.as_euler("ZYX", degrees=True)

        self.state.regulator.pitch = pitch
        self.state.regulator.roll = roll
        self.state.regulator.yaw = yaw

    async def imu_update_loop(self) -> None:
        """Update attitude continuously, independently of the MCU connection."""
        interval = 1.0 / THRUSTER_SEND_FREQUENCY
        next_tick = time.perf_counter() + interval
        while True:
            self.update_regulator_data_from_imu()
            sleep_time = next_tick - time.perf_counter()
            await asyncio.sleep(max(0.0, sleep_time))
            next_tick += interval
            now = time.perf_counter()
            if next_tick < now:
                next_tick = now + interval

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
        self.integral_depth = 0.0

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

        integral_scale = 1.0 - abs(float(heave_input))
        if integral_scale < 0.0:
            integral_scale = 0.0
        elif integral_scale > 1.0:
            integral_scale = 1.0
        self.integral_depth += error * self.delta_t_run_regulator * integral_scale

        if self.integral_depth > DEPTH_INTEGRAL_WINDUP_CLIP:
            self.integral_depth = DEPTH_INTEGRAL_WINDUP_CLIP
        elif self.integral_depth < -DEPTH_INTEGRAL_WINDUP_CLIP:
            self.integral_depth = -DEPTH_INTEGRAL_WINDUP_CLIP

        config = self.state.rov_config.regulator
        depth_regulator_actuation = (
            float(config.depth.kp) * error
            + float(config.depth.ki) * float(self.integral_depth)
            - float(config.depth.kd) * self.state.pressure.depth_change
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

        err_rotvec = r_err.as_rotvec()
        err_x, err_y, err_z = (
            float(err_rotvec[0]),
            float(err_rotvec[1]),
            float(err_rotvec[2]),
        )
        if not (math.isfinite(err_x) and math.isfinite(err_y) and math.isfinite(err_z)):
            err_x = err_y = err_z = 0.0

        ix = float(direction_vector_attitude[0])
        iy = float(direction_vector_attitude[1])
        iz = float(direction_vector_attitude[2])
        integral = self.integral_attitude_rad
        if math.sqrt(ix * ix + iy * iy + iz * iz) < INTEGRAL_RELAX_THRESHOLD:
            integral[0] += err_x * dt
            integral[1] += err_y * dt
            integral[2] += err_z * dt

        clip = _INTEGRAL_WINDUP_CLIP_RAD
        for axis in range(3):
            if integral[axis] > clip:
                integral[axis] = clip
            elif integral[axis] < -clip:
                integral[axis] = -clip

        omega = self.gyro_rad_s

        # PID per axis (roll=x, pitch=y, yaw=z)
        u_roll = (
            config.roll.kp * err_x
            + config.roll.ki * float(integral[0])
            + config.roll.kd * -float(omega[0])
        )
        u_pitch = (
            config.pitch.kp * err_y
            + config.pitch.ki * float(integral[1])
            + config.pitch.kd * -float(omega[1])
        )
        u_yaw = (
            config.yaw.kp * err_z
            + config.yaw.ki * float(integral[2])
            + config.yaw.kd * -float(omega[2])
        )

        stabilization_actuation = self._stabilization_actuation_buffer
        stabilization_actuation[0] = (
            u_pitch / 10.0
        )  # Divide by 10 to avoid unsatisfying PID constant values
        stabilization_actuation[1] = u_yaw / 10.0
        stabilization_actuation[2] = u_roll / 10.0

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
        current_attitude = self.ahrs.current_attitude

        # Remove yaw component from current attitude, because surge should always make ROV move forward relative to body, regardless of yaw
        _yaw, pitch, roll = current_attitude.as_euler("ZYX", degrees=False)
        current_attitude = Rotation.from_euler("ZYX", [0, pitch, roll], degrees=False)

        # Rotating the identity basis by the inverse attitude yields the rotation matrix itself.
        basis_vectors = cast(_F32, current_attitude.as_matrix())

        dir_coeffs = self.state.rov_config.direction_coefficients
        surge_coeff = dir_coeffs.surge if math.isfinite(dir_coeffs.surge) else 1.0
        sway_coeff = dir_coeffs.sway if math.isfinite(dir_coeffs.sway) else 1.0
        heave_coeff = dir_coeffs.heave if math.isfinite(dir_coeffs.heave) else 1.0

        surge_heave_ratio = surge_coeff / heave_coeff if heave_coeff != 0 else 0.0
        sway_heave_ratio = sway_coeff / heave_coeff if heave_coeff != 0 else 0.0
        heave_surge_ratio = heave_coeff / surge_coeff if surge_coeff != 0 else 0.0
        heave_sway_ratio = heave_coeff / sway_coeff if sway_coeff != 0 else 0.0

        surge = float(direction_vector_movement[0])
        sway = float(direction_vector_movement[1])
        heave = float(direction_vector_movement[2])

        world_frame_movement = self._world_frame_movement_buffer
        world_frame_movement[0] = (
            basis_vectors[0][0] * surge
            + basis_vectors[1][0] * sway
            + basis_vectors[2][0] * heave * heave_surge_ratio
        )
        world_frame_movement[1] = (
            basis_vectors[0][1] * surge
            + basis_vectors[1][1] * sway
            + basis_vectors[2][1] * heave * heave_sway_ratio
        )
        world_frame_movement[2] = (
            basis_vectors[0][2] * surge * surge_heave_ratio
            + basis_vectors[1][2] * sway * sway_heave_ratio
            + basis_vectors[2][2] * heave
        )

        return world_frame_movement

    def _scale_direction_vector_with_user_max_power(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Apply the user-configured maximum power percentages to the provided direction vector in place.

        Scales thruster components (indices 0-5) by state.rov_config.power.thrusters_limit / 100.0
        and action components (indices 6-7) by state.rov_config.power.actions_limit / 100.0.

        Parameters:
            direction_vector (numpy.ndarray): Mutable 1-D float32 array (expected length 8) representing the direction vector to be scaled in place.
        """
        thruster_scale = np.float32(
            float(self.state.rov_config.power.thrusters_limit) / 100.0
        )
        direction_vector[0:6] *= thruster_scale

        action_scale = np.float32(
            float(self.state.rov_config.power.actions_limit) / 100.0
        )
        direction_vector[6:8] *= action_scale

    def _scale_regulator_direction_vector(
        self, regulator_direction_vector: NDArray[np.float32]
    ) -> None:
        """Clip the regulator direction vector in-place to the configured per-axis maximum regulator power.

        Parameters:
            regulator_direction_vector (NDArray[np.float32]): Array of regulator outputs (modified in-place). Each element is clamped to the range [-p, p], where p = state.rov_config.power.regulator_limit / 100.0.
        """
        power = float(self.state.rov_config.power.regulator_limit) / 100.0
        _ = np.clip(
            regulator_direction_vector,
            -power,
            power,
            out=regulator_direction_vector,
            dtype=np.float32,
        )

    def apply_regulator_to_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Apply regulator outputs to the provided direction vector and return the pre-limit combined vector.

        This updates internal timing, refreshes regulator targets from user input and edge transitions, computes depth-hold and attitude-stabilization contributions when enabled, captures the combined direction vector before power limits are applied, then scales user and regulator components according to configuration and adds the limited regulator output into the provided direction_vector in place.

        Parameters:
            direction_vector (NDArray[np.float32]): Mutable 8-element NED-format command vector arranged as
                [surge, sway, heave, pitch, yaw, roll, action1, action2]. The array is modified in place:
                - depth hold replaces heave (index 2) with regulator-modified motion and zeroes user heave,
                - attitude stabilization zeroes user pitch/yaw/roll (indices 3:6) and adds regulator corrections,
                - final result is the elementwise sum of the (possibly scaled) user vector and the scaled regulator contributions.

        Returns:
            NDArray[np.float32]: Combined direction vector before user/regulator power limits are applied.
        """
        regulator_direction_vector = self._regulator_direction_vector
        regulator_direction_vector.fill(0.0)

        now = time.time()
        if self.last_run_regulator_time > 0.0:
            self.delta_t_run_regulator = _clamp_dt(now - self.last_run_regulator_time)
        else:
            self.delta_t_run_regulator = _NOMINAL_DT
        self.last_run_regulator_time = now

        self._update_desired_from_direction_vector(direction_vector)
        self._handle_edges()

        if self.state.system_status.depth_hold:
            depth_regulator_actuation = self._handle_depth_hold(
                cast(np.float32, direction_vector[2])
            )
            depth_hold_vector = self._depth_hold_vector_buffer
            depth_hold_vector[:] = (0.0, 0.0, depth_regulator_actuation)
            regulator_direction_vector[0:3] = (
                self._transform_movement_vector_world_to_body(depth_hold_vector)
            )
            direction_vector[2] = 0.0
            movement_vector = self._movement_vector_buffer
            movement_vector[:] = direction_vector[0:3]
            direction_vector[0:3] = self._transform_movement_vector_world_to_body(
                movement_vector
            )

        if self.state.system_status.auto_stabilization:
            stabilization_input = self._stabilization_input_buffer
            stabilization_input[:] = direction_vector[3:6]
            regulator_direction_vector[3:6] = self._handle_stabilization(
                stabilization_input
            )
            direction_vector[3:6] = 0.0

        unlimited_direction_vector = self._unlimited_direction_vector
        unlimited_direction_vector[:] = direction_vector
        unlimited_direction_vector += regulator_direction_vector

        self._scale_regulator_direction_vector(regulator_direction_vector)
        self._scale_direction_vector_with_user_max_power(direction_vector)

        direction_vector += regulator_direction_vector

        return unlimited_direction_vector

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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.SUCCESS,
                content=ToastContent(
                    message_key="toasts_auto_tuning_completed",
                    description_key="toasts_auto_tuning_pid_updated",
                ),
                action=None,
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
                        "yaw", AxisConfig(kp=0, ki=0, kd=0)
                    ),
                )
            )
            queue = get_message_queue()
            queue.put_nowait(suggestions)
            return None

    def _handle_pitch_tuning(self, current_time: float) -> NDArray[np.float32]:
        pitch = self.state.regulator.pitch

        if self.auto_tuning_step == "find_zero":
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "pitch"},
                    description_key="toasts_auto_tuning_finding_zero",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "pitch"},
                    description_key="toasts_auto_tuning_finding_oscillation",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "pitch"},
                    description_key="toasts_auto_tuning_oscillating",
                    description_args={"seconds": int(elapsed)},
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "roll"},
                    description_key="toasts_auto_tuning_finding_zero",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "roll"},
                    description_key="toasts_auto_tuning_finding_oscillation",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "roll"},
                    description_key="toasts_auto_tuning_oscillating",
                    description_args={"seconds": int(elapsed)},
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "depth"},
                    description_key="toasts_auto_tuning_finding_zero",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "depth"},
                    description_key="toasts_auto_tuning_finding_oscillation",
                ),
                action=None,
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
            toast_content(
                identifier=AUTO_TUNING_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_auto_tuning_tuning_phase",
                    message_args={"phase": "depth"},
                    description_key="toasts_auto_tuning_oscillating",
                    description_args={"seconds": int(elapsed)},
                ),
                action=None,
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
            return cast(_F32, a * np.sin(2 * np.pi * f * x + phi) + offset)

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
