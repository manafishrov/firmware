import numpy as np
import time

import config

class PIDController:
    def __init__(self, imu):
        # Desired and last-known states
        self.desired_pitch = 0
        self.desired_roll = 0

        self.previous_pitch = 0
        self.previous_roll = 0

        self.current_dt_pitch = 0
        self.current_dt_roll = 0

        self.integral_value_pitch = 0
        self.integral_value_roll = 0

        # Timing
        self.last_called_time = time.time()

        # TUNING PARAMETERS (loaded from config)
        self.Kp = config.get_Kp()
        self.Ki = config.get_Ki()
        self.Kd = config.get_Kd()
        self.turn_speed = config.get_turn_speed()
        self.EMA_lambda = config.get_EMA_lambda()

        self.imu = imu

    # Setters for gains
    def set_Kp(self, value):
        self.Kp = value

    def set_Ki(self, value):
        self.Ki = value

    def set_Kd(self, value):
        self.Kd = value

    def PID(self, current_value, desired_value, integral_value, derivative_value):
        # Convert all values to radians (necessary for ziegler–nichols method)
        current_value = np.radians(current_value)
        desired_value = np.radians(desired_value)
        integral_value = np.radians(integral_value)
        derivative_value = np.radians(derivative_value)

        error = desired_value - current_value
        return self.Kp * error + self.Ki * integral_value - self.Kd * derivative_value

    def update_desired_pitch_roll(self, pitch_change, roll_change, current_roll, delta_t):

        # Update and clip desired pitch
        self.desired_pitch += pitch_change * self.turn_speed * delta_t
        self.desired_pitch = np.clip(self.desired_pitch, -80, 80)

        # Update and wrap desired roll
        self.desired_roll += roll_change * self.turn_speed * delta_t
        if self.desired_roll > 180:
            self.desired_roll -= 360
        if self.desired_roll < -180:
            self.desired_roll += 360

        # Keep desired_roll relative to current_roll for smooth wrapping
        if self.desired_roll - current_roll > 180:
            self.desired_roll -= 360
        if self.desired_roll - current_roll < -180:
            self.desired_roll += 360

    def regulate_pitch_roll(self, direction_vector):
        # Compute time since last call
        delta_t = time.time() - self.last_called_time
        self.last_called_time = time.time()

        # Read current orientation
        current_pitch, current_roll = self.imu.get_pitch_roll()

        # Update desired setpoints
        desired_pitch_change = direction_vector[3]
        desired_roll_change = direction_vector[5]
        self.update_desired_pitch_roll(desired_pitch_change, desired_roll_change, current_roll, delta_t)

        # Regulate toward those setpoints
        return self.regulate_to_absolute(direction_vector, self.desired_pitch, self.desired_roll, delta_t)



    def regulate_to_absolute(self, direction_vector, target_pitch, target_roll, delta_t):
        # Read actual orientation
        current_pitch, current_roll = self.imu.get_pitch_roll()

        # Update integral error (with anti-windup clipping)
        self.integral_value_pitch += (target_pitch - current_pitch) * delta_t
        self.integral_value_roll  += (target_roll - current_roll) * delta_t

        self.integral_value_pitch = np.clip(self.integral_value_pitch, -100, 100) #THIS VALUE MIGHT NEED TO BE TUNED
        self.integral_value_roll  = np.clip(self.integral_value_roll, -100, 100)

        # Derivative via exponential moving average
        self.current_dt_pitch = (
            self.EMA_lambda * self.current_dt_pitch
            + (1 - self.EMA_lambda) * (current_pitch - self.previous_pitch) / delta_t
        )
        self.current_dt_roll = (
            self.EMA_lambda * self.current_dt_roll
            + (1 - self.EMA_lambda) * (current_roll - self.previous_roll) / delta_t
        )

        # PID outputs
        pitch_actuation = self.PID(current_pitch, target_pitch,
                                   self.integral_value_pitch,
                                   self.current_dt_pitch)
        roll_actuation = self.PID(current_roll, target_roll,
                                  self.integral_value_roll,
                                  self.current_dt_roll)

        # Save for next derivative calc
        self.previous_pitch = current_pitch
        self.previous_roll  = current_roll

        # Build actuation, inverting pitch if upside-down
        if current_roll >= 90 or current_roll <= -90:
            act_pitch = pitch_actuation
        else:
            act_pitch = -pitch_actuation
        act_roll = -roll_actuation

        # Return new direction vector
        return np.array([
            direction_vector[0],
            direction_vector[1],
            direction_vector[2],
            act_pitch,
            direction_vector[4],
            act_roll
        ])

    