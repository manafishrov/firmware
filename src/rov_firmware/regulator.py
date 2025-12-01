"""Regulator module for ROV control."""

from __future__ import annotations

import time
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import curve_fit

from .constants import (
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEGREES,
    AUTO_TUNING_AMPLITUDE_THRESHOLD_DEPTH_METERS,
    AUTO_TUNING_OSCILLATION_DURATION_SECONDS,
    AUTO_TUNING_TOAST_ID,
    AUTO_TUNING_ZERO_THRESHOLD_DEGREES,
    AUTO_TUNING_ZERO_THRESHOLD_DEPTH_METERS,
    COMPLEMENTARY_FILTER_ALPHA,
    DEPTH_DERIVATIVE_EMA_TAU,
    INTEGRAL_WINDUP_CLIP_DEGREES,
    PITCH_MAX,
    ROLL_UPSIDE_DOWN_THRESHOLD,
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


class Regulator:
    """PID regulator for ROV stabilization."""

    def __init__(self, state: RovState):
        """Initialize regulator with ROV state."""
        self.state: RovState = state

        self.gyro: NDArray[np.float32] = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.last_measurement_time: float = 0.0
        self.delta_t: float = 0.0167
        self.previous_depth: float = 0.0
        self.current_dt_depth: float = 0.0

        self.auto_tuning_phase: str = ""
        self.auto_tuning_step: str = ""
        self.auto_tuning_data: list[tuple[float, float]] = []
        self.auto_tuning_params: dict[str, RegulatorPID] = {}
        self.auto_tuning_last_update: float = 0.0
        self.auto_tuning_zero_actuation: float = 0.0
        self.auto_tuning_amplitude: float = 0.0
        self.auto_tuning_oscillation_start: float = 0.0

    def _apply_complementary_filter(
        self,
        current_pitch: float,
        current_roll: float,
        accel_pitch: float,
        accel_roll: float,
    ) -> tuple[float, float]:
        if (
            current_roll >= ROLL_UPSIDE_DOWN_THRESHOLD
            or current_roll <= -ROLL_UPSIDE_DOWN_THRESHOLD
        ):
            current_pitch = (
                COMPLEMENTARY_FILTER_ALPHA
                * (current_pitch + cast(float, self.gyro[1]) * self.delta_t)
                + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_pitch
            )
        else:
            current_pitch = (
                COMPLEMENTARY_FILTER_ALPHA
                * (current_pitch - cast(float, self.gyro[1]) * self.delta_t)
                + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_pitch
            )
        current_roll = (
            COMPLEMENTARY_FILTER_ALPHA
            * (current_roll + cast(float, self.gyro[0]) * self.delta_t)
            + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_roll
        )
        return current_pitch, current_roll

    def _normalize_angles(self, pitch: float, roll: float) -> tuple[float, float]:
        roll = ((roll + ROLL_WRAP_MAX) % 360) - ROLL_WRAP_MAX
        pitch = max(min(pitch, PITCH_MAX), -PITCH_MAX)
        return pitch, roll

    def update_desired_from_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Update desired pitch and roll from direction vector."""
        if self.state.system_status.pitch_stabilization:
            config = self.state.rov_config.regulator
            pitch_change = cast(float, direction_vector[3])
            desired_pitch = (
                self.state.regulator.desired_pitch
                + pitch_change * config.turn_speed * self.delta_t
            )
            desired_pitch = cast(float, np.clip(desired_pitch, -80, 80))
            self.state.regulator.desired_pitch = desired_pitch
        if self.state.system_status.roll_stabilization:
            config = self.state.rov_config.regulator
            roll_change = cast(float, direction_vector[5])
            desired_roll = (
                self.state.regulator.desired_roll
                + roll_change * config.turn_speed * self.delta_t
            )
            if desired_roll > ROLL_WRAP_MAX:
                desired_roll -= 360
            if desired_roll < -ROLL_WRAP_MAX:
                desired_roll += 360
            current_roll = self.state.regulator.roll
            if desired_roll - current_roll > ROLL_WRAP_MAX:
                desired_roll -= 360
            if desired_roll - current_roll < -ROLL_WRAP_MAX:
                desired_roll += 360
            self.state.regulator.desired_roll = desired_roll

    def update_regulator_data_from_imu(self) -> None:
        """Update regulator data from IMU readings."""
        if not self.state.system_health.imu_ok:
            return

        imu_data = self.state.imu
        accel = cast(NDArray[np.float32], imu_data.acceleration)
        gyr = cast(NDArray[np.float32], imu_data.gyroscope)
        self.gyro = np.degrees(gyr)

        now = time.time()
        if self.last_measurement_time > 0:
            self.delta_t = now - self.last_measurement_time
        self.last_measurement_time = now

        current_pitch = self.state.regulator.pitch
        current_roll = self.state.regulator.roll

        accel_pitch = cast(
            float,
            np.degrees(
                cast(
                    float,
                    np.arctan2(
                        cast(float, accel[0]),
                        cast(
                            float,
                            np.sqrt(
                                cast(float, accel[1]) ** 2 + cast(float, accel[2]) ** 2
                            ),
                        ),
                    ),
                )
            ),
        )
        accel_roll = cast(
            float,
            np.degrees(
                cast(
                    float,
                    np.arctan2(cast(float, accel[1]), cast(float, accel[2])),
                ),
            ),
        )

        if accel_roll - current_roll > ROLL_WRAP_MAX:
            current_roll += 360
        if accel_roll - current_roll < -ROLL_WRAP_MAX:
            current_roll -= 360

        current_pitch, current_roll = self._apply_complementary_filter(
            current_pitch,
            current_roll,
            accel_pitch,
            accel_roll,
        )

        current_pitch, current_roll = self._normalize_angles(
            current_pitch, current_roll
        )

        self.state.regulator.pitch = current_pitch
        self.state.regulator.roll = current_roll

    def _handle_depth_hold(self) -> NDArray[np.float32]:
        movement_actuation = np.zeros(3, dtype=np.float32)
        if self.state.system_status.depth_hold:
            current_depth = self.state.pressure.depth
            desired_depth = self.state.regulator.desired_depth
            self.state.regulator.integral_depth -= (
                desired_depth - current_depth
            ) * self.delta_t
            self.state.regulator.integral_depth = np.clip(
                self.state.regulator.integral_depth, -3, 3
            )

            alpha = cast(float, np.exp(-self.delta_t / DEPTH_DERIVATIVE_EMA_TAU))
            self.current_dt_depth = (
                alpha * self.current_dt_depth
                + (1 - alpha) * (current_depth - self.previous_depth) / self.delta_t
            )
            self.previous_depth = current_depth

            config = self.state.rov_config.regulator
            error = -(desired_depth - current_depth)
            heave_actuation = (
                config.depth.kp * error
                + config.depth.ki * self.state.regulator.integral_depth
                + config.depth.kd * self.current_dt_depth
            )

            movement_actuation = self._transform_heave_actuation_from_world_to_body(
                heave_actuation, self.state.regulator.pitch, self.state.regulator.roll
            )
        return movement_actuation

    def _handle_pitch_stabilization(
        self, direction_vector: NDArray[np.float32]
    ) -> float:
        pitch_actuation = 0.0
        if self.state.system_status.pitch_stabilization:
            config = self.state.rov_config.regulator
            desired_pitch = self.state.regulator.desired_pitch

            current_pitch = self.state.regulator.pitch
            integral_scale = cast(
                float, np.clip((1 - abs(cast(float, direction_vector[3]))), 0, 1)
            )
            self.state.regulator.integral_pitch += (
                (desired_pitch - current_pitch) * self.delta_t
            ) * integral_scale
            self.state.regulator.integral_pitch = np.clip(
                self.state.regulator.integral_pitch,
                -INTEGRAL_WINDUP_CLIP_DEGREES,
                INTEGRAL_WINDUP_CLIP_DEGREES,
            )
            pitch_actuation = (
                config.pitch.kp * cast(float, np.radians(desired_pitch - current_pitch))
                + config.pitch.ki
                * cast(float, np.radians(self.state.regulator.integral_pitch))
                - config.pitch.kd * cast(float, np.radians(-cast(float, self.gyro[1])))
            )
            current_roll = self.state.regulator.roll
            if current_roll >= PITCH_MAX or current_roll <= -PITCH_MAX:
                pitch_actuation = -pitch_actuation
        return pitch_actuation

    def _handle_roll_stabilization(
        self, direction_vector: NDArray[np.float32]
    ) -> float:
        roll_actuation = 0.0
        if self.state.system_status.roll_stabilization:
            config = self.state.rov_config.regulator
            desired_roll = self.state.regulator.desired_roll

            current_roll = self.state.regulator.roll
            integral_scale = cast(
                float, np.clip((1 - abs(cast(float, direction_vector[5]))), 0, 1)
            )
            self.state.regulator.integral_roll += (
                (desired_roll - current_roll) * self.delta_t
            ) * integral_scale
            self.state.regulator.integral_roll = np.clip(
                self.state.regulator.integral_roll,
                -INTEGRAL_WINDUP_CLIP_DEGREES,
                INTEGRAL_WINDUP_CLIP_DEGREES,
            )

            roll_actuation = (
                config.roll.kp * cast(float, np.radians(desired_roll - current_roll))
                + config.roll.ki
                * cast(float, np.radians(self.state.regulator.integral_roll))
                - config.roll.kd * cast(float, np.radians(cast(float, self.gyro[0])))
            )
        return roll_actuation

    def _transform_heave_actuation_from_world_to_body(
        self, heave_actuation: float, current_pitch: float, current_roll: float
    ) -> NDArray[np.float32]:
        """Transform heave actuation from world coordinates to body-fixed coordinates, accounting for pitch, roll, and thruster direction coefficients."""
        # Define the actuation vector in world coordinates (z-axis component, heave)
        b = np.array([0, 0, heave_actuation], dtype=np.float32)

        # Calculate trigonometric values for pitch and roll angles
        cp = cast(float, np.cos(cast(float, np.deg2rad(current_pitch))))
        sp = cast(float, np.sin(cast(float, np.deg2rad(current_pitch))))
        cr = cast(float, np.cos(cast(float, np.deg2rad(current_roll))))
        sr = cast(float, np.sin(cast(float, np.deg2rad(current_roll))))

        # Build the rotation matrix from body to world coordinates
        a = np.array(
            [[cp, sp * sr, -sp * cr], [0, cr, sr], [sp, cp * (-sr), cp * cr]],
            dtype=np.float32,
        )

        # Retrieve direction coefficients from configuration
        dir_coeffs = self.state.rov_config.direction_coefficients
        surge_coeff = dir_coeffs.surge
        sway_coeff = dir_coeffs.sway
        heave_coeff = dir_coeffs.heave

        # Normalize coefficients relative to heave and apply minimum thresholds
        if heave_coeff == 0:
            heave_coeff = 1
        surge_coeff /= heave_coeff
        sway_coeff /= heave_coeff
        heave_coeff = 1
        surge_coeff = max(surge_coeff, 0.1)
        sway_coeff = max(sway_coeff, 0.1)
        speed_coeffs = np.diag([surge_coeff, sway_coeff, heave_coeff])
        a = a @ speed_coeffs

        # Solve the linear system to get world coordinate components
        try:
            x = np.linalg.solve(a, b)
        except np.linalg.LinAlgError:
            x, *_ = np.linalg.lstsq(a, b, rcond=None)
        return x

    def _change_coordinate_system_orientation(
        self,
        direction_vector: NDArray[np.float32],
        current_pitch: float,
        current_roll: float,
    ) -> NDArray[np.float32]:
        """Transform orientation actuations from global to body-fixed coordinates."""
        # Actuation values in the global coordinate system
        pitch_g = cast(float, direction_vector[3])
        yaw_g = cast(float, direction_vector[4])
        roll_g = cast(float, direction_vector[5])

        # Retrieving direction coefficients from configuration
        dir_coeffs = self.state.rov_config.direction_coefficients
        pitch_coeff = dir_coeffs.pitch
        yaw_coeff = dir_coeffs.yaw
        roll_coeff = dir_coeffs.roll

        # Calculating sin and cos of pitch and roll angles to be used in transformation
        cp = cast(float, np.cos(cast(float, np.deg2rad(current_pitch))))
        sp = cast(float, np.sin(cast(float, np.deg2rad(current_pitch))))
        cr = cast(float, np.cos(cast(float, np.deg2rad(current_roll))))
        sr = cast(float, np.sin(cast(float, np.deg2rad(current_roll))))

        # This code assumes that the yaw is passed in and thus also passes through this filter.
        try:
            pitch_l = cr * pitch_g + sr * cp * yaw_g * (
                yaw_coeff / pitch_coeff
            )  # Scale so pitch matches yaw
            roll_l = roll_g - sp * yaw_g * (
                yaw_coeff / roll_coeff
            )  # Scale so roll matches yaw
            yaw_l = cr * cp * yaw_g - sr * pitch_g * (
                pitch_coeff / yaw_coeff
            )  # Scale so yaw matches pitch
        except ZeroDivisionError:
            pitch_l, yaw_l, roll_l = pitch_g, yaw_g, roll_g
            log_error(
                "Regulator coordinate system change failed because one of the direction coefficients for pitch, yaw or roll is 0"
            )

        # In the return we leave movement actuation unchanged and only modify orientation actuation
        new_actuation = actuation.copy()
        new_actuation[3] = pitch_l
        new_actuation[4] = yaw_l
        new_actuation[5] = roll_l
        return new_actuation

    def _get_user_scaled_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        scale = self.state.rov_config.power.user_max_power / 100
        return direction_vector * scale

    def _scale_regulator_direction_vector(
        self, regulator_direction_vector: NDArray[np.float32]
    ) -> None:
        power = self.state.rov_config.power.regulator_max_power / 100
        _ = np.clip(
            regulator_direction_vector, -power, power, out=regulator_direction_vector
        )

    def apply_regulator_to_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> None:
        """Get regulator actuation values."""
        regulator_direction_vector = np.zeros(8, dtype=np.float32)

        movement_actuation = self._handle_depth_hold()
        regulator_direction_vector[0:3] = movement_actuation

        pitch_actuation = self._handle_pitch_stabilization(direction_vector)
        regulator_direction_vector[3] = pitch_actuation

        roll_actuation = self._handle_roll_stabilization(direction_vector)
        regulator_direction_vector[5] = roll_actuation

        self._scale_regulator_direction_vector(regulator_direction_vector)

        user_scaled_direction_vector = self._get_user_scaled_direction_vector(
            direction_vector
        )

        if self.state.system_status.pitch_stabilization:
            user_scaled_direction_vector[3] = 0
        if self.state.system_status.roll_stabilization:
            user_scaled_direction_vector[5] = 0

        user_scaled_direction_vector += regulator_direction_vector

        if (
            self.state.system_status.pitch_stabilization
            or self.state.system_status.roll_stabilization
        ):
            user_scaled_direction_vector = self._change_coordinate_system_orientation(
                direction_vector,
                self.state.regulator.pitch,
                self.state.regulator.roll,
            )

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
