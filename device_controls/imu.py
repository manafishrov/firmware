import time
import pybmi2
import numpy as np

import config

#Variables owned by this script
sensor = None
last_measurement_time = time.time()
current_pitch = 0
current_roll = 0

# TUNING PARAMETERS
CF_alpha = config.get_CF_alpha()   

def init_sensor():
    global sensor, last_measurement_time
    sensor = pybmi2.BMI270()
    sensor.set_power_mode(accel=True, gyro=True)

    last_measurement_time = time.time()
    


def get_imu_data():
    global sensor, last_measurement_time, current_pitch, current_roll

    # Check if sensor is initialized
    if sensor is None:
        raise Exception("IMU sensor not initialized.")
    
    # Get sensor data
    accel = sensor.get_accel()  # Returns (x, y, z) in m/s²
    gyro = sensor.get_gyro()    # Returns (x, y, z) in °/s

    # Update time
    delta_t = time.time() - last_measurement_time
    last_measurement_time = time.time()

    # Convert accelerometer data to pitch and roll euler angles
    accel_pitch = 180 * np.arctan2(accel[0], np.sqrt(accel[1]**2 + accel[2]**2)) / np.pi
    accel_roll = 180 * np.arctan2(accel[1], np.sqrt(accel[0]**2 + accel[2]**2)) / np.pi

    # Complementary filter
    current_pitch = CF_alpha * (current_pitch + gyro[0] * delta_t) + (1 - CF_alpha) * accel_pitch
    current_roll = CF_alpha * (current_roll + gyro[1] * delta_t) + (1 - CF_alpha) * accel_roll

    return current_pitch, current_roll
    

def log_imu_data(filename):
    # Adds current pitch, current roll, and last measurment time to a file
    global current_pitch, current_roll, last_measurement_time
    with open(filename, "a") as f:
        f.write(f"{current_pitch}, {current_roll}, {last_measurement_time}\n")

        

    

