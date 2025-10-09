from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

import time
import numpy as np
from numpy.typing import NDArray

COMPLEMENTARY_FILTER_ALPHA = 0.98
GYRO_HIGH_PASS_FILTER_TAU = 0.1
DEPTH_DERIVATIVE_EMA_TAU = 0.064


class Regulator:
    def __init__(self, state: RovState):
        self.state: RovState = state

        self.prev_gyro = None
        self.filtered_gyro = np.array([0.0, 0.0, 0.0])
        self.last_measurement_time = time.time()
        self.integral_value_pitch = 0.0
        self.integral_value_roll = 0.0
        self.integral_value_depth = 0.0
        self.previous_depth = 0.0
        self.current_dt_depth = 0.0

    def update_data(self):
        if not self.state.system_health.imu_ok:
            return

        imu_data = self.state.imu
        accel = np.array(imu_data.acceleration)
        gyr = np.array(imu_data.gyroscope)
        gyro = np.degrees(gyr)

        now = time.time()
        delta_t = now - self.last_measurement_time
        self.last_measurement_time = now

        if self.prev_gyro is None:
            self.filtered_gyro = gyro.copy()
        else:
            alpha = GYRO_HIGH_PASS_FILTER_TAU / (GYRO_HIGH_PASS_FILTER_TAU + delta_t)
            self.filtered_gyro = alpha * (self.filtered_gyro + gyro - self.prev_gyro)
        self.prev_gyro = gyro.copy()

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

        current_roll = ((current_roll + 180) % 360) - 180
        current_pitch = max(min(current_pitch, 90), -90)

        self.state.regulator.pitch = current_pitch
        self.state.regulator.roll = current_roll

        if not self.state.system_status.pitch_stabilization:
            self.state.regulator.desired_pitch = current_pitch
        if not self.state.system_status.roll_stabilization:
            self.state.regulator.desired_roll = current_roll

    def stabilize(self, direction_vector: NDArray[np.float64]) -> NDArray[np.float64]:
        delta_t = time.time() - self.last_measurement_time

        config = self.state.rov_config.regulator
        dir_coeffs = self.state.rov_config.direction_coefficients
        power = self.state.rov_config.power.regulator_max_power

        if self.state.system_status.depth_stabilization:
            self.state.regulator.desired_depth = self.state.pressure.depth
            self.integral_value_depth = 0.0

        if self.state.system_status.pitch_stabilization:
            pitch_change = direction_vector[3]
            desired_pitch = (
                self.state.regulator.desired_pitch
                + pitch_change * config.turn_speed * delta_t
            )
            desired_pitch = np.clip(desired_pitch, -80, 80)
            self.state.regulator.desired_pitch = desired_pitch

        if self.state.system_status.roll_stabilization:
            roll_change = direction_vector[5]
            desired_roll = (
                self.state.regulator.desired_roll
                + roll_change * config.turn_speed * delta_t
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

        regulator_actuation = np.zeros(6)

        if self.state.system_status.depth_stabilization:
            current_depth = self.state.pressure.depth
            desired_depth = self.state.regulator.desired_depth
            self.integral_value_depth += (desired_depth - current_depth) * delta_t
            self.integral_value_depth = np.clip(self.integral_value_depth, -3, 3)

            alpha = np.exp(-delta_t / DEPTH_DERIVATIVE_EMA_TAU)
            self.current_dt_depth = (
                alpha * self.current_dt_depth
                + (1 - alpha) * (current_depth - self.previous_depth) / delta_t
            )
            self.previous_depth = current_depth

            error = -(desired_depth - current_depth)
            actuation = (
                config.depth.kp * error
                + config.depth.ki * self.integral_value_depth
                - config.depth.kd * self.current_dt_depth
            )

            b = np.array([0, 0, actuation])
            current_pitch = self.state.regulator.pitch
            current_roll = self.state.regulator.roll
            cp = np.cos(np.deg2rad(current_pitch))
            sp = np.sin(np.deg2rad(current_pitch))
            cr = np.cos(np.deg2rad(current_roll))
            sr = np.sin(np.deg2rad(current_roll))

            A = np.array(
                [[cp, sp * sr, -sp * cr], [0, cr, sr], [sp, cp * (-sr), cp * cr]]
            )
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

            regulator_actuation[0:3] = x

        if self.state.system_status.pitch_stabilization:
            current_pitch = self.state.regulator.pitch
            desired_pitch = self.state.regulator.desired_pitch
            self.integral_value_pitch += (desired_pitch - current_pitch) * delta_t
            self.integral_value_pitch = np.clip(self.integral_value_pitch, -100, 100)
            pitch_actuation = (
                config.pitch.kp * (desired_pitch - current_pitch)
                + config.pitch.ki * self.integral_value_pitch
                - config.pitch.kd * -self.filtered_gyro[1]
            )
            current_roll = self.state.regulator.roll
            if current_roll >= 90 or current_roll <= -90:
                pitch_actuation = -pitch_actuation
            regulator_actuation[3] = pitch_actuation

        if self.state.system_status.roll_stabilization:
            current_roll = self.state.regulator.roll
            desired_roll = self.state.regulator.desired_roll
            self.integral_value_roll += (desired_roll - current_roll) * delta_t
            self.integral_value_roll = np.clip(self.integral_value_roll, -100, 100)
            roll_actuation = (
                config.roll.kp * (desired_roll - current_roll)
                + config.roll.ki * self.integral_value_roll
                - config.roll.kd * self.filtered_gyro[0]
            )
            regulator_actuation[5] = roll_actuation

        max_val = np.max(np.abs(regulator_actuation))
        if max_val > power:
            regulator_actuation *= power / max_val

        direction_vector[0:6] += regulator_actuation

        return direction_vector
