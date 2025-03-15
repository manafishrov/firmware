import time
import numpy as np
from mpu6050 import mpu6050

import config

# Variables owned by this script
sensor = None
last_measurement_time = time.time()
current_pitch = 0
current_roll = 0

# Highpass global variables
prev_gyro = None
filtered_gyro = None

# TUNING PARAMETERS
CF_alpha = config.get_CF_alpha()  
GYRO_HPF_tau = config.get_GYRO_HPF_tau()  

def init_sensor():
    global sensor, last_measurement_time
    
    sensor = mpu6050(0x68)
    print("--- IMU initialization finished! ---")

    last_measurement_time = time.time()
    

def update_pitch_roll():
    global sensor, last_measurement_time, current_pitch, current_roll, prev_gyro, filtered_gyro

    # Check if sensor is initialized
    if sensor is None:
        raise Exception("IMU sensor not initialized.")
    
    # Get sensor data
    accel = sensor.get_accel_data()  # Returns dictionary with (x, y, z) in m/s²
    accel = np.array([accel["x"], accel["y"], accel["z"]])
    gyro = sensor.get_gyro_data()    # Returns dictionary with (x, y, z) in °/s
    gyro = np.array([gyro["x"], gyro["y"], gyro["z"]])

    # Update time
    delta_t = time.time() - last_measurement_time
    last_measurement_time = time.time()

    # Highpass filter, to remove constant error from gyro data
    if prev_gyro is None:
        filtered_gyro = gyro
    else:
        hpf_alpha = GYRO_HPF_tau / (GYRO_HPF_tau + delta_t)
        filtered_gyro = hpf_alpha * (filtered_gyro + gyro - prev_gyro)
    prev_gyro = gyro.copy()

    # Convert accelerometer data to pitch and roll euler angles
    accel_pitch = np.degrees(np.arctan2(accel[0], np.sqrt(accel[1]**2 + accel[2]**2))) # Pitch angle that ranges between -90 and 90 degrees
    accel_roll = np.degrees(np.arctan2(accel[1], accel[2])) # Roll angle between -180 and 180 degrees

    # 1: This makes sure the complimentary filter uses accelerometer data in the right way even when doing a full rotation
    # and going from -180 to 180 degrees
    if accel_roll - current_roll > 180:
        current_roll += 360

    if accel_roll - current_roll < -180:
        current_roll -= 360

    # Complementary filter, pitch is updated with different gyro direction depening on if sensor is upside down or not
    if current_roll >= 0:
        current_pitch = CF_alpha * (current_pitch - filtered_gyro[1] * delta_t) + (1 - CF_alpha) * accel_pitch
    else:
        current_pitch = CF_alpha * (current_pitch + filtered_gyro[1] * delta_t) + (1 - CF_alpha) * accel_pitch
    
    current_roll = CF_alpha * (current_roll - filtered_gyro[0] * delta_t) + (1 - CF_alpha) * accel_roll

    # Adjust roll back to be between -180 and 180 degrees
    if current_roll > 180:
        current_roll -= 360
    if current_roll < -180:
        current_roll += 360

    # Adjust pitch back to be between -90 and 90 degrees
    if current_pitch > 90:
        current_pitch = 90 - (current_pitch - 90)
    if current_pitch < -90:
        current_pitch = -90 + (current_pitch - 90)


def get_pitch_roll():
    global current_pitch, current_roll
    return current_pitch, current_roll

def get_yaw_gyro():
    global sensor
    gyro = sensor.get_gyro_data()    # Returns (x, y, z) in °/s
    return gyro[2]
    

def log_imu_data(filename):
    # Adds current pitch, current roll, and last measurment time to a file
    global current_pitch, current_roll, last_measurement_time
    with open(filename, "a") as f:
        f.write(f"{current_pitch}, {current_roll}, {last_measurement_time}\n")

        

    

