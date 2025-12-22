"""Regulator module for ROV control (TEST VERSION: self-contained new params/state)."""

# This regulator uses the NED convention.
# Direction vector represents [surge, sway, heave, pitch, yaw, roll, action1, action2], where action1 and action2 are unused by this code.

from __future__ import annotations

import time
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import curve_fit
from scipy.spatial.transform import Rotation as R

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
    DT_MAX_SECONDS,
    DT_MIN_SECONDS,
    INTEGRAL_RELAX_THRESHOLD,
    INTEGRAL_WINDUP_CLIP_DEGREES,
    PITCH_MAX,
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
# PARAMETERS TO BE ADDED TO CONFIG AND SETTINGS, REMOVE WHEN APPLICATION UPDATED
# =============================================================================

# Depth hold behavior
TEST_DEPTH_HOLD_SETPOINT_RATE_MPS: float = 0.5 # HOW QUICKLY DEPTH CHANGES WHEN DEPTH HOLD ENABLED

# Yaw PID gains (kept inside this file; independent from config)
TEST_YAW_KP: float = 0.5
TEST_YAW_KI: float = 0.0
TEST_YAW_KD: float = 0.1


def _clamp_dt(dt: float) -> float: # For extra redundancy
    if not np.isfinite(dt):
        return 0.0167
    return float(np.clip(dt, DT_MIN_SECONDS, DT_MAX_SECONDS))


class _MahonyAhrs:
    """Mahony AHRS (gyro + accel) in quaternion form.

    - Stabilizes roll/pitch with accel (gravity).
    - Yaw is integrated from gyro (will drift without external heading reference).
    """

    def __init__(self, kp: float, ki: float) -> None:
        self.kp: float = float(kp)
        self.ki: float = float(ki)
        self._integral: NDArray[np.float64] = np.zeros(3, dtype=np.float64)
        self.current_attitude: R = R.identity()

    def reset(self) -> None:
        self._integral[:] = 0.0
        self.current_attitude = R.identity()

    def update(
        self,
        gyro_rad_s: NDArray[np.float32],
        accel: NDArray[np.float32],
        dt: float,
    ) -> None:
        """Update attitude reading with gyro (rad/s) and accel (m/s²) readings."""
        dt = _clamp_dt(dt)

        ax, ay, az = float(accel[0]), float(accel[1]), float(accel[2])
        a_norm = float(np.sqrt(ax * ax + ay * ay + az * az))
        if not np.isfinite(a_norm) or a_norm < AHRS_ACCEL_MIN_NORM: # If accel reading is crazy coco loco, integrate gyro only
            self._integrate_gyro_only(gyro_rad_s, dt)
            return

        a = -np.array([ax, ay, az], dtype=np.float64) / a_norm # - In front to follow NED convention

        # Estimated "up" direction in body frame from current attitude (the reason we use up is that this is the expected accel from gravity).
        g_body = self.current_attitude.inv().apply(np.array([0.0, 0.0, 1.0], dtype=np.float64))

        # Error drives estimated up toward measured accel direction.
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

    def _integrate_gyro_only(self, gyro_rad_s: NDArray[np.float32], dt: float) -> None: #Called by update
        omega = np.array(
            [float(gyro_rad_s[0]), float(gyro_rad_s[1]), float(gyro_rad_s[2])],
            dtype=np.float64,
        )
        self._integrate_omega(omega, dt)

    def _integrate_omega(self, omega_rad_s: NDArray[np.float64], dt: float) -> None: #Called by update

        dtheta = omega_rad_s * float(dt)
        dR = R.from_rotvec(dtheta)
        self.current_attitude = self.current_attitude * dR  # body-to-world update

        q = self.current_attitude.as_quat()
        q /= np.linalg.norm(q)
        self.current_attitude = R.from_quat(q)


class Regulator:
    """PID regulator for ROV stabilization."""

    def __init__(self, state: RovState):
        """Initialize the Regulator with ROV state.

        Args:
            state: The RovState object containing the current ROV state and configuration.
        """
        self.state: RovState = state

        self.gyro_rad_s: NDArray[np.float32] = np.array([0.0, 0.0, 0.0], dtype=np.float32)  # rad/s

        self.last_update_ahrs_time: float = 0.0
        self.delta_t_update_ahrs: float = 0.0167
        self.last_run_regulator_time: float = 0.0
        self.delta_t_run_regulator: float = 0.0167

        self.previous_depth: float = 0.0
        self.current_dt_depth: float = 0.0

        # Quaternion attitude estimator
        self.ahrs: _MahonyAhrs = _MahonyAhrs(kp=AHRS_MAHONY_KP, ki=AHRS_MAHONY_KI)

        self.desired_attitude: R = R.identity()
        self.integral_attitude_rad: NDArray[np.float32] = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        # Edge detection for resetting when enabling regulators
        self._prev_depth_hold_enabled: bool = False
        self._prev_stabilization_enabled: bool = False


        # Auto tuning fields (kept as-is)
        self.auto_tuning_phase: str = ""
        self.auto_tuning_step: str = ""
        self.auto_tuning_data: list[tuple[float, float]] = []
        self.auto_tuning_params: dict[str, RegulatorPID] = {}
        self.auto_tuning_last_update: float = 0.0
        self.auto_tuning_zero_actuation: float = 0.0
        self.auto_tuning_amplitude: float = 0.0
        self.auto_tuning_oscillation_start: float = 0.0


    def _update_desired_from_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Update desired attitude quaternion from direction vector."""
        if self.state.system_status.depth_hold:
            heave_change = float(direction_vector[2])
            desired_depth = float(self.state.regulator.desired_depth) + heave_change * TEST_DEPTH_HOLD_SETPOINT_RATE_MPS * self.delta_t_run_regulator
            self.state.regulator.desired_depth = float(desired_depth)

        if self.state.system_status.pitch_stabilization: #CHANGE TO GENERAL STABILIZATION WHEN IMPLEMENTED IN APP
            # Update the desired quaternion, use quaternion math, here would be the place to check if the FPV mode is enabled

            # Yaw change
            desired_yaw_change = direction_vector[4] * self.delta_t_run_regulator * self.state.rov_config.regulator.turn_speed
            yaw_rotation = R.from_rotvec([0.0, 0.0, np.deg2rad(desired_yaw_change)]) # Yaw rate scaled down
            self.desired_attitude = yaw_rotation * self.desired_attitude

            # Pitch change
            desired_pitch_change = direction_vector[3] * self.delta_t_run_regulator * self.state.rov_config.regulator.turn_speed
            pitch, yaw, roll = self.desired_attitude.as_euler("YZX", degrees=True)
            pitch = pitch + float(desired_pitch_change)
            pitch = float(np.clip(pitch, -PITCH_MAX, PITCH_MAX)) # Clipping pitch to avoid gimbal lock
            self.desired_attitude = R.from_euler("YZX", [pitch, yaw, roll], degrees=True)

            # Roll change
            desired_roll_change = direction_vector[5] * self.delta_t_run_regulator * self.state.rov_config.regulator.turn_speed
            roll_rotation = R.from_rotvec([np.deg2rad(desired_roll_change), 0.0, 0.0])
            self.desired_attitude = self.desired_attitude * roll_rotation

            # Updating desired pitch, roll, yaw in state for app visualization
            pitch, yaw, roll = self.desired_attitude.as_euler("YZX", degrees=True)
            self.state.regulator.desired_pitch = pitch
            self.state.regulator.desired_roll = roll
            #self.state.regulator.desired_yaw = yaw TEMPORARY COMMENTED, IMPLEMENT LATER


    # -------------------------------------------------------------------------
    # Public API (must keep name/signature): update_regulator_data_from_imu
    # -------------------------------------------------------------------------
    def update_regulator_data_from_imu(self) -> None:
        """Update regulator data from IMU readings (quaternion AHRS)."""
        if not self.state.system_health.imu_ok:
            return

        # Retrieve IMU data
        imu_data = self.state.imu
        accel = cast(NDArray[np.float32], imu_data.acceleration)
        gyr = cast(NDArray[np.float32], imu_data.gyroscope)

        self.gyro_rad_s = gyr

        # Compute delta_t
        now = time.time()
        if self.last_update_ahrs_time > 0.0:
            self.delta_t_update_ahrs = _clamp_dt(now - self.last_update_ahrs_time)
        else:
            self.delta_t_update_ahrs = 0.0167
        self.last_update_ahrs_time = now

        # Update AHRS attitude quaternion
        self.ahrs.update(gyr, accel, self.delta_t_update_ahrs)

        # Getting euler angles from quaternion for visualization in app. 
        roll, pitch, yaw = self.ahrs.current_attitude.as_euler("XYZ", degrees=True)

        self.state.regulator.pitch = pitch
        self.state.regulator.roll = roll
        #self.state.regulator.yaw = yaw TEMPOSRARY - implement later


    def _handle_edges(self) -> None:
        depth_hold_enabled = self.state.system_status.depth_hold
        stabilization_enabled = self.state.system_status.pitch_stabilization # TEMPORARY - change to general stabilization instead of pitch only

        if depth_hold_enabled and not self._prev_depth_hold_enabled:
            self._depth_hold_enable_edge()
        if stabilization_enabled and not self._prev_stabilization_enabled:
            self._attitude_enable_edge()

        self._prev_depth_hold_enabled = depth_hold_enabled
        self._prev_stabilization_enabled = stabilization_enabled


    # -------------------------------------------------------------------------
    # Depth hold internals
    # -------------------------------------------------------------------------
    def _depth_hold_enable_edge(self) -> None: # Note to Michael: I know this is done in another script too, but it is better to do here because we have to change the integral terms which are only in this class, and in future we might need to have more complex behaviour on edges.
        current_depth = self.state.pressure.depth
        self.state.regulator.desired_depth = current_depth
        self.state.regulator.integral_depth = 0.0
        self.current_dt_depth = 0.0
        self.previous_depth = current_depth

    def _handle_depth_hold(self, heave_input: float) -> float:
        current_depth = self.state.pressure.depth
        desired_depth = self.state.regulator.desired_depth

        # Update error
        error = current_depth - desired_depth  # positive => too deep => command up

        # Update integral term
        integral_scale = np.clip((1.0 - abs(heave_input)), 0.0, 1.0) # Stick-based integral relaxation, higher input -> less integral accumulation
        self.state.regulator.integral_depth += error * self.delta_t_run_regulator * integral_scale # Integrate depth error
        self.state.regulator.integral_depth = np.clip(self.state.regulator.integral_depth, -DEPTH_INTEGRAL_WINDUP_CLIP, DEPTH_INTEGRAL_WINDUP_CLIP) # Windup prevention

        # Update derivative term (using EMA filter)
        alpha = np.exp(-self.delta_t_run_regulator / float(DEPTH_DERIVATIVE_EMA_TAU))
        raw_rate = (current_depth - self.previous_depth) / self.delta_t_run_regulator
        self.current_dt_depth = alpha * self.current_dt_depth + (1.0 - alpha) * float(raw_rate)
        self.previous_depth = current_depth

        # PID computation to get actuation
        config = self.state.rov_config.regulator
        depth_regulator_actuation = (
            float(config.depth.kp) * error
            + float(config.depth.ki) * float(self.state.regulator.integral_depth) 
            + float(config.depth.kd) * float(self.current_dt_depth)
        )

        return float(depth_regulator_actuation)

    # -------------------------------------------------------------------------
    # Attitude stabilization internals
    # -------------------------------------------------------------------------
    def _attitude_enable_edge(self) -> None:
        # Set desired attitude pitch and roll to 0 and yaw to current yaw 
        self.desired_attitude = R.identity()
        current_yaw = self.ahrs.current_attitude.as_euler("YZX", degrees=False)[1]
        yaw_rotation = R.from_rotvec([0.0, 0.0, current_yaw])
        self.desired_attitude = yaw_rotation * self.desired_attitude

        # Reset I terms
        self.integral_attitude_rad[:] = 0.0




    def _handle_stabilization(self, direction_vector_attitude: NDArray[np.float32]) -> NDArray[np.float32]:
        # Here will be the quaternion-based PID stabilization for pitch, roll, yaw
        """Quaternion-based PID attitude stabilization.

        Returns actuation vector in order: [pitch, yaw, roll].
        """
        dt = self.delta_t_run_regulator
        config = self.state.rov_config.regulator

        current_attitude: R = self.ahrs.current_attitude
        desired_attitude: R = self.desired_attitude

        # Calculate attitude error quaternion
        R_err = current_attitude.inv() * desired_attitude

        # Convert to rotation vector, the rotation vector describes the error as rotations around the xyz axes in the body frame
        err_rotvec = R_err.as_rotvec()
        if not np.all(np.isfinite(err_rotvec)):
            err_rotvec = np.zeros(3, dtype=np.float32)

        # Update integral term
        if np.linalg.norm(direction_vector_attitude[0:3]) < INTEGRAL_RELAX_THRESHOLD: # Setpoint-based / stick-based integral relax. Stop integrating if input over threshold
            self.integral_attitude_rad += err_rotvec * dt

        clip_rad = float(np.deg2rad(INTEGRAL_WINDUP_CLIP_DEGREES))
        self.integral_attitude_rad = np.clip(self.integral_attitude_rad, -clip_rad, clip_rad) # Windup prevention

        # Gyro body rates in rad/s
        omega = self.gyro_rad_s.astype(np.float32, copy=False)

        # PID per axis (roll=x, pitch=y, yaw=z)
        u_roll  = config.roll.kp  * err_rotvec[0] + config.roll.ki  * self.integral_attitude_rad[0] + config.roll.kd  * (-omega[0])
        u_pitch = config.pitch.kp * err_rotvec[1] + config.pitch.ki * self.integral_attitude_rad[1] + config.pitch.kd * (-omega[1])
        u_yaw   = TEST_YAW_KP   * err_rotvec[2] + TEST_YAW_KI   * self.integral_attitude_rad[2] + TEST_YAW_KD   * (-omega[2])

        stabilization_actuation = np.array([u_pitch, u_yaw, u_roll], dtype=np.float32)/100.0  # Divided by 100 to avoid having annoyingly small PID constant values

        return stabilization_actuation


    # -------------------------------------------------------------------------
    # Frame transforms using quaternion attitude and direction coefficients
    # -------------------------------------------------------------------------

    def _transform_movement_vector_world_to_body(self, direction_vector_movement: NDArray[np.float32]) -> NDArray[np.float32]: # Must be completely rewritten
        """Transform movement vector from world frame to body frame, applying direction coefficients."""
        surge_movement_world = np.array([direction_vector_movement[0], 0, 0])
        sway_movement_world = np.array([0, direction_vector_movement[1], 0])
        heave_movement_world = np.array([0, 0, direction_vector_movement[2]])

        current_attitude = self.ahrs.current_attitude

        # Remove yaw component from current attitude, because surge should always make ROV move forward relative to body, regardless of yaw
        roll, pitch, yaw = current_attitude.as_euler("XYZ", degrees=False)
        current_attitude = R.from_euler("XYZ", [roll, pitch, 0], degrees=False) 

        # Transforming movements from world to body frame
        surge_movement_body = current_attitude.inv().apply(surge_movement_world)
        sway_movement_body = current_attitude.inv().apply(sway_movement_world)
        heave_movement_body = current_attitude.inv().apply(heave_movement_world)

        # Impoting direction coefficients
        dir_coeffs = self.state.rov_config.direction_coefficients
        surge_coeff = dir_coeffs.surge if np.isfinite(dir_coeffs.surge) and dir_coeffs.surge > 0 else 1.0
        sway_coeff = dir_coeffs.sway if np.isfinite(dir_coeffs.sway) and dir_coeffs.sway > 0 else 1.0
        heave_coeff = dir_coeffs.heave if np.isfinite(dir_coeffs.heave) and dir_coeffs.heave > 0 else 1.0

        # Scaling movements according to direction coefficients
        surge_movement_body *= np.array([1.0, 1.0, surge_coeff/heave_coeff])
        sway_movement_body *= np.array([1.0, 1.0, sway_coeff/heave_coeff])
        heave_movement_body *= np.array([heave_coeff/surge_coeff, heave_coeff/sway_coeff, 1.0])

        # Combining movements
        world_frame_movement = surge_movement_body + sway_movement_body + heave_movement_body

        return world_frame_movement.astype(np.float32, copy=False)


    # -------------------------------------------------------------------------
    # Scaling/clipping 
    # -------------------------------------------------------------------------
    def _scale_direction_vector_with_user_max_power(self, direction_vector: NDArray[np.float32]) -> None:
        scale = float(self.state.rov_config.power.user_max_power) / 100.0
        direction_vector *= np.float32(scale)

    def _scale_regulator_direction_vector(self, regulator_direction_vector: NDArray[np.float32]) -> None:
        power = float(self.state.rov_config.power.regulator_max_power) / 100.0
        _ = np.clip(regulator_direction_vector, -power, power, out=regulator_direction_vector)

    # -------------------------------------------------------------------------
    # Main function: apply_regulator_to_direction_vector
    # -------------------------------------------------------------------------
    def apply_regulator_to_direction_vector(self, direction_vector: NDArray[np.float32]) -> None:
        """Apply regulator actuation to direction vector in-place."""
        regulator_direction_vector = np.zeros(8, dtype=np.float32)

        # Compute delta_t
        now = time.time()
        if self.last_run_regulator_time> 0.0:
            self.delta_t_run_regulator = _clamp_dt(now - self.last_run_regulator_time)
        else:
            self.delta_t_run_regulator = 0.0167
        self.last_run_regulator_time = now

        self._update_desired_from_direction_vector(direction_vector)
        self._handle_edges() # Initializes parameters to right values if stabilization or depth hold just turned on

        # Applying regulators
        if self.state.system_status.depth_hold:
            # The regulator direction vector and direction vector are updated seperately because they need to be scaled seperately
            depth_regulator_actuation = self._handle_depth_hold(float(direction_vector[2]))
            regulator_direction_vector[0:3] = self._transform_movement_vector_world_to_body(np.array([0.0, 0.0, float(depth_regulator_actuation)], dtype=np.float32))
            direction_vector[2] = 0.0
            direction_vector[0:3] = self._transform_movement_vector_world_to_body(direction_vector[0:3].copy())

        if self.state.system_status.pitch_stabilization:
            regulator_direction_vector[3:6] = self._handle_stabilization(direction_vector[3:6].copy())
            direction_vector[3:6] = 0.0

        # Scaling according to values specified in settings by user
        self._scale_regulator_direction_vector(regulator_direction_vector)
        self._scale_direction_vector_with_user_max_power(direction_vector)

        # Adding regulator output to direction vector
        direction_vector += regulator_direction_vector


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
