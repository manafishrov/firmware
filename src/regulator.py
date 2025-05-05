import numpy as np
import time

import imu
import config

# Variables owned by this script
desired_pitch = 0
desired_roll = 0

previous_pitch = 0
previous_roll = 0

current_dt_pitch = 0
current_dt_roll = 0

integral_value_pitch = 0
integral_value_roll = 0

last_called_time = time.time()

# TUNING PARAMETERS
Kp = config.get_Kp()
Ki = config.get_Ki()
Kd = config.get_Kd()

def set_Kp(value):
    global Kp
    Kp = value

def set_Ki(value):
    global Ki  
    Ki = value

def set_Kd(value):
    global Kd
    Kd = value

turn_speed = config.get_turn_speed()
EMA_lambda = config.get_EMA_lambda()

def PID(current_value, desired_value, integral_value, derivative_value):
    # Convert all values to radians (neccesary for ziegle-nichols method to work)
    current_value = np.radians(current_value)
    desired_value = np.radians(desired_value)
    integral_value = np.radians(integral_value)
    derivative_value = np.radians(derivative_value)

    error = desired_value - current_value
    return Kp * error + Ki * integral_value - Kd * derivative_value

def update_desired_pitch_roll(pitch_change, roll_change, current_roll, delta_t):
    # To completely finish this function, i need to know the range of the pitch and roll values from the IMU
    global desired_pitch, desired_roll, integral_value_pitch, integral_value_roll

    # Reset integral values
    integral_value_pitch = 0
    integral_value_roll = 0

    # Update and clip desired pitch
    desired_pitch += pitch_change * turn_speed * delta_t
    desired_pitch = np.clip(desired_pitch, -80, 80)
    
    # Update and loop desired roll
    desired_roll += roll_change * turn_speed * delta_t
    if desired_roll > 180:
        desired_roll -= 360
    if desired_roll < -180:
        desired_roll += 360

    # Updating desired with regards to current roll to allow looping angles
    if desired_roll - current_roll > 180:
        desired_roll -= 360
    if desired_roll - current_roll < -180:
        desired_roll += 360



def regulate_pitch_roll(direction_vector):
    global current_dt_pitch, current_dt_roll, previous_pitch, previous_roll, integral_value_pitch, integral_value_roll, last_called_time

    # Update time
    delta_t = time.time() - last_called_time
    last_called_time = time.time()

    # Get current pitch and roll values from the IMU
    current_pitch, current_roll = imu.get_pitch_roll()


    # Update desired pitch and roll values
    desired_pitch_change = direction_vector[3]
    desired_roll_change = direction_vector[5]
    update_desired_pitch_roll(desired_pitch_change, desired_roll_change, current_roll, delta_t)

    # Update integral values
    integral_value_pitch += (desired_pitch - current_pitch) * delta_t
    integral_value_roll  += (desired_roll - current_roll) * delta_t

    # Make sure the integral values don't get too big, prevent windup
    integral_value_pitch = np.clip(integral_value_pitch, -100, 100)
    integral_value_roll = np.clip(integral_value_roll, -100, 100)

    # Calculate derivative values using exponential moving average
    current_dt_pitch = EMA_lambda * current_dt_pitch + (1-EMA_lambda)*(current_pitch-previous_pitch)/delta_t
    current_dt_roll = EMA_lambda * current_dt_roll + (1-EMA_lambda)*(current_roll-previous_roll)/delta_t

    # Calculate actuation for pitch and roll using PID
    pitch_actuation = PID(current_pitch, desired_pitch, integral_value_pitch, current_dt_pitch)
    roll_actuation = PID(current_roll, desired_roll, integral_value_roll, current_dt_roll)

    # Update previous pitch and roll values
    previous_pitch = current_pitch
    previous_roll = current_roll

    # Put the actuation values into the direction vector, if upside down, the pitch actuation is inverted
    if current_roll >= 90 or current_roll <= -90:
        actuation_vector = np.array([0, 0, 0, -pitch_actuation, 0, roll_actuation])
    else:
        actuation_vector = np.array([0, 0, 0, pitch_actuation, 0, roll_actuation])

    #Cursed i know, but it works.
    return np.array([direction_vector[0], direction_vector[1], direction_vector[2], actuation_vector[3], direction_vector[4], actuation_vector[5]])


# A function similar to the previous one, but insted of getting user input it regulates to an absolute specified value.
# Good for tuning parameters or resetting ROV position to neutral.  
def regulate_to_absolute(direction_vector, target_pitch, target_roll):
    global current_dt_pitch, current_dt_roll, previous_pitch, previous_roll, integral_value_pitch, integral_value_roll, last_called_time

    # Update time
    delta_t = time.time() - last_called_time
    last_called_time = time.time()

    # Get current pitch and roll values from the IMU
    current_pitch, current_roll = imu.get_pitch_roll()

    # Update integral values
    integral_value_pitch += (target_pitch - current_pitch) * delta_t
    integral_value_roll  += (target_roll - current_roll) * delta_t
    
    # Calculate derivative values using exponential moving average
    current_dt_pitch = EMA_lambda * current_dt_pitch + (1-EMA_lambda)*(current_pitch-previous_pitch)/delta_t
    current_dt_roll = EMA_lambda * current_dt_roll + (1-EMA_lambda)*(current_roll-previous_roll)/delta_t

    # Calculate actuation for pitch and roll using PID
    pitch_actuation = PID(current_pitch, target_pitch, integral_value_pitch, current_dt_pitch)
    roll_actuation = PID(current_roll, target_roll, integral_value_roll, current_dt_roll)

    # Update previous pitch and roll values
    previous_pitch = current_pitch
    previous_roll = current_roll

    # Had to do it this way because of some weird python comy list stuff i dont understand, but this worked!
    return np.array([0, 0, 0, pitch_actuation, 0, roll_actuation]) 

    
    







