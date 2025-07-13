import numpy as np
import time

import config

class PIDController:
    def __init__(self, imu):
        # Desired and last-known states
        self.desired_pitch = 0
        self.desired_roll = 0

        self.integral_value_pitch = 0
        self.integral_value_roll = 0

        # Timing
        self.last_called_time = time.time()

        # TUNING PARAMETERS (loaded from config)
        self.Kp_pitch = config.get_Kp_pitch()
        self.Ki_pitch = config.get_Ki_pitch()
        self.Kd_pitch = config.get_Kd_pitch()

        self.Kp_roll = config.get_Kp_roll()
        self.Ki_roll = config.get_Ki_roll() 
        self.Kd_roll = config.get_Kd_roll()

        self.turn_speed = config.get_turn_speed()

        self.ptc = config.get_pitch_turn_coefficient()
        self.ytc = config.get_yaw_turn_coefficient()
        self.rtc = config.get_roll_turn_coefficient()

        self.imu = imu

    def PID(self, current_value, desired_value, integral_value, derivative_value, type):
        # Convert all values to radians (necessary for ziegler–nichols method)
        current_value = np.radians(current_value)
        desired_value = np.radians(desired_value)
        integral_value = np.radians(integral_value)
        derivative_value = np.radians(derivative_value)

        error = desired_value - current_value

        if type == "pitch":
            Kp = self.Kp_pitch
            Ki = self.Ki_pitch
            Kd = self.Kd_pitch
        elif type == "roll":
            Kp = self.Kp_roll
            Ki = self.Ki_roll
            Kd = self.Kd_roll

        return Kp * error + Ki * integral_value - Kd * derivative_value
    
    def change_cooridinate_system(self, direction_vector, pitch, roll):
        pitch_g, yaw_g, roll_g = direction_vector[3], direction_vector[4], direction_vector[5]

        cp, sp = np.cos(np.deg2rad(pitch)), np.sin(np.deg2rad(pitch))
        cr, sr = np.cos(np.deg2rad(roll)), np.sin(np.deg2rad(roll))

        try:
            pitch_l =  cr*pitch_g  + sr*cp*yaw_g * (self.ytc/self.ptc)  # Here we scale so pitch matches yaw
            roll_l  =  roll_g      - sp*yaw_g    * (self.ytc/self.rtc)  # Here we scale so roll matches yaw
            yaw_l   =  cr*cp*yaw_g - sr*pitch_g  * (self.ptc/self.ytc)  # Here we scale so yaw matches pitch
        except ZeroDivisionError:
            pitch_l, yaw_l, roll_l = pitch_g, yaw_g, roll_g
            print("Regulator coordinate system change failed because one of the turn coefficients is 0")

        return np.array([direction_vector[0], direction_vector[1], direction_vector[2], pitch_l, yaw_l, roll_l])

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

        # New, much better way of calculating derivative
        self.current_dt_pitch, self.current_dt_roll = self.imu.get_pitch_roll_gyro()

        # PID outputs
        pitch_actuation = self.PID(current_pitch, target_pitch, self.integral_value_pitch, self.current_dt_pitch, "pitch")
        roll_actuation = self.PID(current_roll, target_roll, self.integral_value_roll, self.current_dt_roll, "roll")

        # Build actuation, inverting pitch if upside-down
        if current_roll >= 90 or current_roll <= -90:
            pitch_actuation = -pitch_actuation
        
        direction_vector = [0, 0, 0, pitch_actuation, direction_vector[4], roll_actuation]

        direction_vector = self.change_cooridinate_system(direction_vector, current_pitch, current_roll)

        # Return new direction vector
        return direction_vector

    