import numpy as np
import time

import config

class DepthHoldController:
    def __init__(self, pressure_sensor, imu):
        # Desired and last-known states
        self.desired_depth = 1

        self.integral_value_depth = 0

        self.previous_depth = 1

        self.current_dt_depth = 0
        self.EMA_tau = 0.064  # Cutoff frequency of 2.5Hz for depth derivative

        # Timing
        self.last_called_time = time.time()

        # TUNING PARAMETERS (loaded from config)
        self.Kp_depth = config.get_Kp_depth()
        self.Ki_depth = config.get_Ki_depth()
        self.Kd_depth = config.get_Kd_depth()

        self.pressure_sensor = pressure_sensor
        self.imu = imu

    def update_desired_depth(self, new_depth):
        self.desired_depth = new_depth
        self.integral_value_depth = 0

    def PID(self, current_value, desired_value, integral_value, derivative_value):
        error = desired_value - current_value
        return self.Kp_depth * error + self.Ki_depth * integral_value - self.Kd_depth * derivative_value

    def regulate_depth(self):
        # Compute time since last call
        delta_t = time.time() - self.last_called_time
        self.last_called_time = time.time()

        # Read current orientation
        current_depth = self.pressure_sensor.depth()  

        # Update integral error (with anti-windup clipping)
        self.integral_value_depth += (self.desired_depth - current_depth) * delta_t

        self.integral_value_depth = np.clip(self.integral_value_depth, -3, 3) #THIS VALUE MIGHT NEED TO BE TUNED

        # Derivative via exponential moving average
        alpha = np.exp(-delta_t / self.EMA_tau)
        self.current_dt_depth = (
            alpha * self.current_dt_depth
            + (1 - alpha) * (current_depth - self.previous_depth) / delta_t
        )
        self.previous_depth = current_depth
  
        # PID outputs
        actuation = self.PID(current_depth, self.desired_depth, self.integral_value_depth, self.current_dt_depth)
        
        # Use IMU data to map actuation onto direction vector containing [forward, side, up, pitch, yaw, roll]
        #TODO: Implement this, the hard part....
        pitch, roll = self.imu.get_pitch_roll()

        # Return new direction vector
        return np.array([0, 0, 0, act_pitch, 0, act_roll])

    