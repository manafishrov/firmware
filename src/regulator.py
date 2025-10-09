from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from rov_state import RovState
    from numpy.typing import NDArray

import numpy as np
from scipy.optimize import curve_fit
from .log import log_info, log_error
from .toast import toast_loading, toast_success
from .models.config import RegulatorPID
from .constants import (
    COMPLEMENTARY_FILTER_ALPHA,
    GYRO_HIGH_PASS_FILTER_TAU,
    DEPTH_DERIVATIVE_EMA_TAU,
    AUTO_TUNING_TOAST_ID,
)


class Regulator:
    def __init__(self, state: RovState):
        self.state: RovState = state

        self.prev_gyro: Optional[np.ndarray] = None
        self.filtered_gyro: np.ndarray = np.array([0.0, 0.0, 0.0])
        self.previous_imu_measurement: float = 0.0
        self.imu_measurement_delta: float = 0.01
        self.integral_value_pitch: float = 0.0
        self.integral_value_roll: float = 0.0
        self.integral_value_depth: float = 0.0
        self.previous_depth: float = 0.0
        self.current_dt_depth: float = 0.0

        self.auto_tuning_phase: str = ""
        self.auto_tuning_step: str = ""
        self.auto_tuning_data: list = []
        self.auto_tuning_params: dict = {}
        self.auto_tuning_last_update: float = 0.0
        self.auto_tuning_zero_actuation: float = 0.0
        self.auto_tuning_amplitude: float = 0.0
        self.auto_tuning_oscillation_start: float = 0.0

    def _filter_gyro_data(self, gyro: np.ndarray, delta_t: float) -> np.ndarray:
        if self.prev_gyro is None:
            self.filtered_gyro = gyro.copy()
        else:
            alpha = GYRO_HIGH_PASS_FILTER_TAU / (GYRO_HIGH_PASS_FILTER_TAU + delta_t)
            self.filtered_gyro = alpha * (self.filtered_gyro + gyro - self.prev_gyro)
        self.prev_gyro = gyro.copy()
        return self.filtered_gyro

    def _apply_complementary_filter(
        self,
        current_pitch: float,
        current_roll: float,
        accel_pitch: float,
        accel_roll: float,
        delta_t: float,
    ) -> tuple[float, float]:
        if current_roll >= 90 or current_roll <= -90:
            current_pitch = (
                COMPLEMENTARY_FILTER_ALPHA
                * (current_pitch + self.filtered_gyro[1] * delta_t)
                + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_pitch
            )
        else:
            current_pitch = (
                COMPLEMENTARY_FILTER_ALPHA
                * (current_pitch - self.filtered_gyro[1] * delta_t)
                + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_pitch
            )
        current_roll = (
            COMPLEMENTARY_FILTER_ALPHA
            * (current_roll + self.filtered_gyro[0] * delta_t)
            + (1 - COMPLEMENTARY_FILTER_ALPHA) * accel_roll
        )
        return current_pitch, current_roll

    def _normalize_angles(self, pitch: float, roll: float) -> tuple[float, float]:
        roll = ((roll + 180) % 360) - 180
        pitch = max(min(pitch, 90), -90)
        return pitch, roll

    def _update_regulator_data(self, pitch: float, roll: float):
        self.state.regulator.pitch = pitch
        self.state.regulator.roll = roll
        if not self.state.system_status.pitch_stabilization:
            self.state.regulator.desired_pitch = pitch
        if not self.state.system_status.roll_stabilization:
            self.state.regulator.desired_roll = roll

    def update_data(self):
        if not self.state.system_health.imu_ok:
            return

        imu_data = self.state.imu
        accel = np.array(imu_data.acceleration)
        gyr = np.array(imu_data.gyroscope)
        gyro = np.degrees(gyr)

        if self.previous_imu_measurement > 0:
            self.imu_measurement_delta = (
                self.state.imu.measured_at - self.previous_imu_measurement
            )
        else:
            self.imu_measurement_delta = 0.01
        self.previous_imu_measurement = self.state.imu.measured_at

        self._filter_gyro_data(gyro, self.imu_measurement_delta)

        current_pitch = self.state.regulator.pitch
        current_roll = self.state.regulator.roll

        accel_pitch = np.degrees(
            np.arctan2(accel[0], np.sqrt(accel[1] ** 2 + accel[2] ** 2))
        )
        accel_roll = np.degrees(np.arctan2(accel[1], accel[2]))

        if accel_roll - current_roll > 180:
            current_roll += 360
        if accel_roll - current_roll < -180:
            current_roll -= 360

        current_pitch, current_roll = self._apply_complementary_filter(
            current_pitch,
            current_roll,
            accel_pitch,
            accel_roll,
            self.imu_measurement_delta,
        )

        current_pitch, current_roll = self._normalize_angles(
            current_pitch, current_roll
        )

        self._update_regulator_data(current_pitch, current_roll)

    def _handle_depth_stabilization(self) -> np.ndarray:
        actuation = np.zeros(3)
        if self.state.system_status.depth_stabilization:
            if self.state.regulator.desired_depth == 0.0:
                self.state.regulator.desired_depth = self.state.pressure.depth
                self.integral_value_depth = 0.0

            current_depth = self.state.pressure.depth
            desired_depth = self.state.regulator.desired_depth
            self.integral_value_depth += (
                desired_depth - current_depth
            ) * self.imu_measurement_delta
            self.integral_value_depth = np.clip(self.integral_value_depth, -3, 3)

            alpha = np.exp(-self.imu_measurement_delta / DEPTH_DERIVATIVE_EMA_TAU)
            self.current_dt_depth = (
                alpha * self.current_dt_depth
                + (1 - alpha)
                * (current_depth - self.previous_depth)
                / self.imu_measurement_delta
            )
            self.previous_depth = current_depth

            config = self.state.rov_config.regulator
            error = -(desired_depth - current_depth)
            depth_actuation = (
                config.depth.kp * error
                + config.depth.ki * self.integral_value_depth
                - config.depth.kd * self.current_dt_depth
            )

            actuation = self._compute_thrust_allocation(
                depth_actuation, self.state.regulator.pitch, self.state.regulator.roll
            )
        return actuation

    def _handle_pitch_stabilization(
        self, direction_vector: NDArray[np.float64]
    ) -> float:
        actuation = 0.0
        if self.state.system_status.pitch_stabilization:
            config = self.state.rov_config.regulator
            pitch_change = direction_vector[3]
            desired_pitch = (
                self.state.regulator.desired_pitch
                + pitch_change * config.turn_speed * self.imu_measurement_delta
            )
            desired_pitch = np.clip(desired_pitch, -80, 80)
            self.state.regulator.desired_pitch = desired_pitch

            current_pitch = self.state.regulator.pitch
            self.integral_value_pitch += (
                desired_pitch - current_pitch
            ) * self.imu_measurement_delta
            self.integral_value_pitch = np.clip(self.integral_value_pitch, -100, 100)
            actuation = (
                config.pitch.kp * (desired_pitch - current_pitch)
                + config.pitch.ki * self.integral_value_pitch
                - config.pitch.kd * -self.filtered_gyro[1]
            )
            current_roll = self.state.regulator.roll
            if current_roll >= 90 or current_roll <= -90:
                actuation = -actuation
        return actuation

    def _handle_roll_stabilization(
        self, direction_vector: NDArray[np.float64]
    ) -> float:
        actuation = 0.0
        if self.state.system_status.roll_stabilization:
            config = self.state.rov_config.regulator
            roll_change = direction_vector[5]
            desired_roll = (
                self.state.regulator.desired_roll
                + roll_change * config.turn_speed * self.imu_measurement_delta
            )
            if desired_roll > 180:
                desired_roll -= 360
            if desired_roll < -180:
                desired_roll += 360
            current_roll = self.state.regulator.roll
            if desired_roll - current_roll > 180:
                desired_roll -= 360
            if desired_roll - current_roll < -180:
                desired_roll += 360
            self.state.regulator.desired_roll = desired_roll

            self.integral_value_roll += (
                desired_roll - current_roll
            ) * self.imu_measurement_delta
            self.integral_value_roll = np.clip(self.integral_value_roll, -100, 100)
            actuation = (
                config.roll.kp * (desired_roll - current_roll)
                + config.roll.ki * self.integral_value_roll
                - config.roll.kd * self.filtered_gyro[0]
            )
        return actuation

    def _compute_thrust_allocation(
        self, actuation: float, current_pitch: float, current_roll: float
    ) -> np.ndarray:
        b = np.array([0, 0, actuation])
        cp = np.cos(np.deg2rad(current_pitch))
        sp = np.sin(np.deg2rad(current_pitch))
        cr = np.cos(np.deg2rad(current_roll))
        sr = np.sin(np.deg2rad(current_roll))

        A = np.array([[cp, sp * sr, -sp * cr], [0, cr, sr], [sp, cp * (-sr), cp * cr]])
        dir_coeffs = self.state.rov_config.direction_coefficients
        forward_coeff = dir_coeffs.horizontal
        sideways_coeff = dir_coeffs.strafe
        upward_coeff = dir_coeffs.vertical
        if upward_coeff == 0:
            upward_coeff = 1
        forward_coeff /= upward_coeff
        sideways_coeff /= upward_coeff
        upward_coeff = 1
        if forward_coeff < 0.1:
            forward_coeff = 0.1
        if sideways_coeff < 0.1:
            sideways_coeff = 0.1
        speed_coeffs = np.diag([forward_coeff, sideways_coeff, upward_coeff])
        A = A @ speed_coeffs

        try:
            x = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            x, *_ = np.linalg.lstsq(A, b, rcond=None)
        return x

    def _scale_regulator_actuation(self, actuation: np.ndarray) -> np.ndarray:
        power = self.state.rov_config.power.regulator_max_power
        max_val = np.max(np.abs(actuation))
        if max_val > power:
            actuation *= power / max_val
        return actuation

    def _apply_actuation_to_direction_vector(
        self, direction_vector: NDArray[np.float64], actuation: np.ndarray
    ):
        direction_vector[0:6] += actuation

    def stabilize(self, direction_vector: NDArray[np.float64]) -> NDArray[np.float64]:
        regulator_actuation = np.zeros(6)

        depth_actuation = self._handle_depth_stabilization()
        regulator_actuation[0:3] = depth_actuation

        pitch_actuation = self._handle_pitch_stabilization(direction_vector)
        regulator_actuation[3] = pitch_actuation

        roll_actuation = self._handle_roll_stabilization(direction_vector)
        regulator_actuation[5] = roll_actuation

        regulator_actuation = self._scale_regulator_actuation(regulator_actuation)
        self._apply_actuation_to_direction_vector(direction_vector, regulator_actuation)

        return direction_vector

    def handle_auto_tuning(
        self, current_time: float
    ) -> tuple[Optional[NDArray[np.float64]], bool]:
        if not self.state.regulator.auto_tuning_active:
            return None, False

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
            return np.zeros(6), False

        self.auto_tuning_last_update = current_time

        if self.auto_tuning_phase == "pitch":
            return self._handle_pitch_tuning(current_time), False
        elif self.auto_tuning_phase == "roll":
            return self._handle_roll_tuning(current_time), False
        elif self.auto_tuning_phase == "depth":
            return self._handle_depth_tuning(current_time), False
        else:
            self.state.regulator.auto_tuning_active = False
            toast_success(
                id=AUTO_TUNING_TOAST_ID,
                message="Auto tuning completed",
                description="PID parameters updated",
                cancel=None,
            )
            log_info("Regulator auto tuning completed")
            return None, True

    def _handle_pitch_tuning(self, current_time: float) -> NDArray[np.float64]:
        pitch = self.state.regulator.pitch

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning pitch",
                description="Finding zero point...",
                cancel=None,
            )
            if abs(pitch) < 3:
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Pitch zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += 0.001 if pitch > 0 else -0.001
                return np.array([0, 0, 0, self.auto_tuning_zero_actuation, 0, 0])

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
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
            if abs(pitch) > 30:
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Pitch amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, 0, actuation, 0, 0])

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= 10:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("pitch")
                return np.zeros(6)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if pitch > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            self.auto_tuning_data.append((current_time, pitch))
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning pitch",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, 0, actuation, 0, 0])

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "roll"
            self.auto_tuning_step = "find_zero"
            self.auto_tuning_data = []
            self.auto_tuning_zero_actuation = 0.0
            self.auto_tuning_amplitude = 0.0
            log_info("Pitch tuning complete, starting roll")
            return np.zeros(6)

        return np.zeros(6)

    def _handle_roll_tuning(self, current_time: float) -> NDArray[np.float64]:
        roll = self.state.regulator.roll
        pitch = self.state.regulator.pitch

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning roll",
                description="Finding zero point...",
                cancel=None,
            )
            if abs(roll) < 3:
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Roll zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += 0.001 if roll > 0 else -0.001
                pitch_comp = -pitch * self.state.rov_config.regulator.pitch.kp * 0.5
                return np.array(
                    [0, 0, 0, pitch_comp, 0, self.auto_tuning_zero_actuation]
                )

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
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
            if abs(roll) > 30:
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Roll amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, 0, pitch_comp, 0, actuation])

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= 10:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("roll")
                return np.zeros(6)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if roll > 0
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            pitch_comp = -pitch * self.state.rov_config.regulator.pitch.kp * 0.5
            self.auto_tuning_data.append((current_time, roll))
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning roll",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, 0, pitch_comp, 0, actuation])

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "depth"
            self.auto_tuning_step = "find_zero"
            self.auto_tuning_data = []
            self.auto_tuning_zero_actuation = 0.0
            self.auto_tuning_amplitude = 0.0
            log_info("Roll tuning complete, starting depth")
            return np.zeros(6)

        return np.zeros(6)

    def _handle_depth_tuning(self, current_time: float) -> NDArray[np.float64]:
        depth = self.state.pressure.depth

        if self.auto_tuning_step == "find_zero":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning depth",
                description="Finding zero point...",
                cancel=None,
            )
            if abs(depth - self.state.regulator.desired_depth) < 0.1:
                self.auto_tuning_step = "find_amplitude"
                log_info(
                    f"Depth zero found at actuation {self.auto_tuning_zero_actuation}"
                )
            else:
                self.auto_tuning_zero_actuation += (
                    0.001 if depth > self.state.regulator.desired_depth else -0.001
                )
                return np.array([0, 0, self.auto_tuning_zero_actuation, 0, 0, 0])

        elif self.auto_tuning_step == "find_amplitude":
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
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
            if abs(depth - self.state.regulator.desired_depth) > 0.5:
                self.auto_tuning_step = "oscillate"
                self.auto_tuning_oscillation_start = current_time
                log_info(f"Depth amplitude found: {self.auto_tuning_amplitude}")
            return np.array([0, 0, actuation, 0, 0, 0])

        elif self.auto_tuning_step == "oscillate":
            elapsed = current_time - self.auto_tuning_oscillation_start
            if elapsed >= 10:
                self.auto_tuning_step = "fit_curve"
                self._fit_curve("depth")
                return np.zeros(6)
            actuation = (
                self.auto_tuning_zero_actuation + self.auto_tuning_amplitude
                if depth > self.state.regulator.desired_depth
                else self.auto_tuning_zero_actuation - self.auto_tuning_amplitude
            )
            self.auto_tuning_data.append((current_time, depth))
            toast_loading(
                id=AUTO_TUNING_TOAST_ID,
                message="Tuning depth",
                description=f"Oscillating... {int(elapsed)}s",
                cancel=None,
            )
            return np.array([0, 0, actuation, 0, 0, 0])

        elif self.auto_tuning_step == "fit_curve":
            self.auto_tuning_phase = "done"
            log_info("Depth tuning complete")
            return np.zeros(6)

        return np.zeros(6)

    def _fit_curve(self, axis: str):
        if not self.auto_tuning_data:
            log_error(f"No data for {axis} curve fitting")
            return

        times, values = zip(*self.auto_tuning_data)
        times = np.array(times) - times[0]
        values = np.array(values)

        def sine_wave(x, A, f, phi, offset):
            return A * np.sin(2 * np.pi * f * x + phi) + offset

        try:
            params, _ = curve_fit(
                sine_wave,
                times,
                values,
                p0=[(np.max(values) - np.min(values)) / 2, 1 / 10, 0, np.mean(values)],
            )
            A, f, _, _ = params
            T_u = 1 / f
            K_u = (4 * self.auto_tuning_amplitude) / (np.pi * A)
            K_p = 0.6 * K_u
            K_i = 1.2 * K_u / T_u
            K_d = 0.075 * K_u * T_u
            self.auto_tuning_params[axis] = RegulatorPID(kp=K_p, ki=K_i, kd=K_d)
            log_info(f"{axis} PID: Kp={K_p:.3f}, Ki={K_i:.3f}, Kd={K_d:.3f}")
        except Exception as e:
            log_error(f"Curve fitting failed for {axis}: {e}")
            self.auto_tuning_params[axis] = RegulatorPID(kp=0, ki=0, kd=0)
