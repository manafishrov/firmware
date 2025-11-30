"""This script tests that the BMI270 IMU is working correctly by reading and printing accelerometer, gyroscope, and temperature data."""

import logging
import time

from bmi270.BMI270 import (
    ACC_BWP_NORMAL,
    ACC_ODR_100,
    ACC_RANGE_2G,
    BMI270,
    GYR_BWP_NORMAL,
    GYR_ODR_100,
    GYR_RANGE_1000,
    I2C_PRIM_ADDR,
    PERFORMANCE_MODE,
)


def main() -> None:
    """Run the IMU test script."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
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

    try:
        while True:
            acc_data = imu.get_acc_data()
            gyr_data = imu.get_gyr_data()
            temp_data = imu.get_temp_data()
            logger.info(f"Acc: {acc_data}, Gyr: {gyr_data}, Temp: {temp_data}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
