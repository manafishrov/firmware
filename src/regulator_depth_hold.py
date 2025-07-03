import numpy as np
import time

import config

class DepthHoldController:
    def __init__(self, pressure_sensor):
        # Desired and last-known states
        self.desired_depth = 0

        self.integral_value_depth = 0

        # Timing
        self.last_called_time = time.time()

        # TUNING PARAMETERS (loaded from config)
        self.Kp_depth = config.get_Kp_depth()
        self.Ki_depth = config.get_Ki_depth()
        self.Kd_depth = config.get_Kd_depth()

        self.pressure_sensor = pressure_sensor

    def PID(self, current_value, desired_value, integral_value, derivative_value, type):

        error = desired_value - current_value #CAME THIS FAR

        if type == "pitch":
            Kp = self.Kp_pitch
            Ki = self.Ki_pitch
            Kd = self.Kd_pitch
        elif type == "roll":
            Kp = self.Kp_roll
            Ki = self.Ki_roll
            Kd = self.Kd_roll

        return Kp * error + Ki * integral_value - Kd * derivative_value

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
        current_pitch, current_roll = self.imu.get_pitch_roll() # TODO: Place update call here

        # Update integral error (with anti-windup clipping)
        self.integral_value_pitch += (target_pitch - current_pitch) * delta_t
        self.integral_value_roll  += (target_roll - current_roll) * delta_t

        self.integral_value_pitch = np.clip(self.integral_value_pitch, -100, 100) #THIS VALUE MIGHT NEED TO BE TUNED
        self.integral_value_roll  = np.clip(self.integral_value_roll, -100, 100)

        # New, much better way of calculating derivative
        self.current_dt_pitch, self.current_dt_roll = self.imu.get_pitch_roll_gyro()

        # PID outputs
        pitch_actuation = self.PID(current_pitch, target_pitch, self.integral_value_pitch, self.current_dt_pitch, "pitch")
        roll_actuation = self.PID(current_roll, target_roll, self.integral_value_roll, self.current_dt_roll, "roll")

        # Build actuation, inverting pitch if upside-down
        if current_roll >= 90 or current_roll <= -90:
            act_pitch = -pitch_actuation
        else:
            act_pitch = -pitch_actuation
        
        act_roll = roll_actuation

        # Return new direction vector
        return np.array([0, 0, 0, act_pitch, 0, act_roll])

    