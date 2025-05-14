import time
import numpy as np

import config
from bmi270 import *

class IMU:
    def __init__(self):
        # Initialize sensor and settings
        self.sensor = BMI270(0x68)
        self.sensor.load_config_file()
        self.sensor.set_mode(PERFORMANCE_MODE)
        self.sensor.set_acc_range(ACC_RANGE_2G)
        self.sensor.set_gyr_range(GYR_RANGE_1000)
        self.sensor.set_acc_odr(ACC_ODR_100)
        self.sensor.set_gyr_odr(GYR_ODR_100)
        self.sensor.set_acc_bwp(ACC_BWP_NORMAL)
        self.sensor.set_gyr_bwp(GYR_BWP_NORMAL)
        self.sensor.disable_fifo_header()
        self.sensor.enable_data_streaming()
        self.sensor.enable_acc_filter_perf()
        self.sensor.enable_gyr_noise_perf()
        self.sensor.enable_gyr_filter_perf()
        print("--- IMU initialization finished! ---")

        # Timing and state
        self.last_measurement_time = time.time()
        self.current_pitch = 0.0
        self.current_roll = 0.0
        self.prev_gyro = None
        self.filtered_gyro = None

        # Filter parameters
        self.CF_alpha = config.get_CF_alpha()
        self.GYRO_HPF_tau = config.get_GYRO_HPF_tau()

    def update_pitch_roll(self):
        # Read data
        accel = self.sensor.get_acc_data()  # (x, y, z) in m/s²
        gyr = self.sensor.get_gyr_data()    # (x, y, z) in rad/s
        gyro = np.degrees(np.array([gyr[0], gyr[1], gyr[2]]))

        # Compute delta time
        now = time.time()
        delta_t = now - self.last_measurement_time
        self.last_measurement_time = now

        # High-pass filter on gyro
        if self.prev_gyro is None:
            self.filtered_gyro = gyro.copy()
        else:
            alpha = self.GYRO_HPF_tau / (self.GYRO_HPF_tau + delta_t)
            self.filtered_gyro = alpha * (self.filtered_gyro + gyro - self.prev_gyro)
        self.prev_gyro = gyro.copy()

        # Accelerometer angles
        accel_pitch = np.degrees(np.arctan2(accel[0], np.sqrt(accel[1]**2 + accel[2]**2)))
        accel_roll = np.degrees(np.arctan2(accel[1], accel[2]))

        # Handle wrap-around for roll
        if accel_roll - self.current_roll > 180:
            self.current_roll += 360
        if accel_roll - self.current_roll < -180:
            self.current_roll -= 360

        # Complementary filter
        if self.current_roll >= 90 or self.current_roll <= -90:
            self.current_pitch = (
                self.CF_alpha * (self.current_pitch + self.filtered_gyro[1] * delta_t)
                + (1 - self.CF_alpha) * accel_pitch
            )
        else:
            self.current_pitch = (
                self.CF_alpha * (self.current_pitch - self.filtered_gyro[1] * delta_t)
                + (1 - self.CF_alpha) * accel_pitch
            )
        self.current_roll = (
            self.CF_alpha * (self.current_roll + self.filtered_gyro[0] * delta_t)
            + (1 - self.CF_alpha) * accel_roll
        )

        # Normalize angles
        self.current_roll = ((self.current_roll + 180) % 360) - 180
        self.current_pitch = max(min(self.current_pitch,  90), -90)

    def get_pitch_roll(self):
        return self.current_pitch, self.current_roll

    def get_yaw_gyro(self):
        gyr = self.sensor.get_gyr_data()
        return np.degrees(gyr[2])

    def log_data(self, filename):
        with open(filename, 'a') as f:
            f.write(f"{self.current_pitch}, {self.current_roll}, {self.last_measurement_time}\n")


if __name__ == "__main__":
    imu = IMU()
    while True:
        imu.update()
        print(f"Pitch: {imu.current_pitch}, Roll: {imu.current_roll}")
        time.sleep(1)