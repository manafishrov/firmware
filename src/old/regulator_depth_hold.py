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

        self.forward_speed_coefficient = config.get_forward_speed_coefficient()
        self.upward_speed_coefficient = config.get_upward_speed_coefficient()
        self.sideways_speed_coefficient = config.get_sideways_speed_coefficient()

        if self.upward_speed_coefficient == 0:
            print("Depth hold will not work when upward speed coefficient is 0! Unexpected behaviour likely to occur.")
            self.upward_speed_coefficient = 1

        # Normalizing speed coeficcients, scale so that upwards becomes 1 and their ratio stays the same
        # FOR SETTINGS: Upwards can not be 0
        self.forward_speed_coefficient /= self.upward_speed_coefficient
        self.sideways_speed_coefficient /= self.upward_speed_coefficient
        self.upward_speed_coefficient = 1

        # If any are 0, set them to a value to avoid zero division error
        if self.forward_speed_coefficient < 0.1:
            self.forward_speed_coefficient = 0.1
        if self.sideways_speed_coefficient < 0.1:
            self.sideways_speed_coefficient = 0.1

        self.pressure_sensor = pressure_sensor
        self.imu = imu

    def update_desired_depth(self, new_depth):
        self.desired_depth = new_depth
        self.integral_value_depth = 0

    def PID(self, current_value, desired_value, integral_value, derivative_value):
        error = -(desired_value - current_value)
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
        pitch, roll = self.imu.get_pitch_roll()

        # This vector represents desired direction in global coordinates
        b = np.array([0, 0, actuation])


        cp, sp = np.cos(np.deg2rad(pitch)), np.sin(np.deg2rad(pitch))
        cr, sr = np.cos(np.deg2rad(roll)),    np.sin(np.deg2rad(roll))

        # In this matrix columns are equal to the vector form of which way each of the directions we can move take us
        # First column is forward, second is side, third is up
        A = np.array([
        [cp, sp*sr,    -sp*cr],
        [0,  cr,       sr],
        [sp, cp*(-sr), cp*cr]
        ])

        speed_coefficients = np.diag([
            self.forward_speed_coefficient,
            self.sideways_speed_coefficient,
            self.upward_speed_coefficient
        ])

        A = A @ speed_coefficients

        # Solve for direction vector "x"
        try:
            x = np.linalg.solve(A, b)
        except np.linalg.LinAlgError as e:
            print(f"Error solving linear system for depth hold thrust allocation: {e}, using least squares instead.")
            x, *_ = np.linalg.lstsq(A, b, rcond=None)

        # Return new direction vector (formatted as [forward, side, up, pitch, yaw, roll])
        return np.array([x[0], x[1], x[2], 0, 0, 0])

    