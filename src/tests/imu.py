# This script tests that the BMI270 IMU is working correctly by reading and printing accelerometer, gyroscope, and temperature data.

import time
from bmi270.BMI270 import *


def main() -> None:
    print("Initializing IMU...")
    imu = BMI270(I2C_PRIM_ADDR)
    imu.load_config_file()
    imu.set_mode(PERFORMANCE_MODE)
    imu.set_acc_range(ACC_RANGE_2G)
    imu.set_gyr_range(GYR_RANGE_1000)
    imu.set_acc_odr(ACC_ODR_100)
    imu.set_gyr_odr(GYR_ODR_100)
    imu.set_acc_bwp(ACC_BWP_NORMAL)
    imu.set_gyr_bwp(GYR_BWP_NORMAL)
    imu.disable_fifo_header()
    imu.enable_data_streaming()
    imu.enable_acc_filter_perf()
    imu.enable_gyr_noise_perf()
    imu.enable_gyr_filter_perf()

    print("Reading IMU data. Press Ctrl+C to stop.")
    try:
        while True:
            acc = imu.get_acc_data()
            gyr = imu.get_gyr_data()
            temp = imu.get_temp_data()
            print(f"ACC: {acc} m/s^2 | GYR: {gyr} rad/s | TEMP: {temp:.2f} C")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nTest ended.")


if __name__ == "__main__":
    main()
