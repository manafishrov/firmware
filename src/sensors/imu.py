"""IMU sensor interface for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rov_state import RovState

import asyncio

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
import numpy as np

from ..constants import SYSTEM_FAILURE_THRESHOLD
from ..log import log_error, log_info
from ..models.sensors import ImuData
from ..toast import toast_error


class Imu:
    """IMU sensor class."""

    def __init__(self, state: RovState):
        """Initialize the IMU sensor.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.imu: BMI270 | None = None

    async def initialize(self) -> None:
        """Initialize the BMI270 IMU sensor with performance settings."""
        try:
            log_info("Attempting to initialize BMI270 IMU...")

            imu_instance = await asyncio.to_thread(BMI270, I2C_PRIM_ADDR)
            await asyncio.to_thread(imu_instance.load_config_file)
            await asyncio.to_thread(imu_instance.set_mode, PERFORMANCE_MODE)
            await asyncio.to_thread(imu_instance.set_acc_range, ACC_RANGE_2G)
            await asyncio.to_thread(imu_instance.set_gyr_range, GYR_RANGE_1000)
            await asyncio.to_thread(imu_instance.set_acc_odr, ACC_ODR_100)
            await asyncio.to_thread(imu_instance.set_gyr_odr, GYR_ODR_100)
            await asyncio.to_thread(imu_instance.set_acc_bwp, ACC_BWP_NORMAL)
            await asyncio.to_thread(imu_instance.set_gyr_bwp, GYR_BWP_NORMAL)
            await asyncio.to_thread(imu_instance.disable_fifo_header)
            await asyncio.to_thread(imu_instance.enable_data_streaming)
            await asyncio.to_thread(imu_instance.enable_acc_filter_perf)
            await asyncio.to_thread(imu_instance.enable_gyr_noise_perf)
            await asyncio.to_thread(imu_instance.enable_gyr_filter_perf)

            self.imu = imu_instance
            self.state.system_health.imu_ok = True
            log_info("BMI270 IMU initialized successfully.")

        except Exception as e:
            self.state.system_health.imu_ok = False
            log_error(f"Failed to initialize BMI270 IMU. Is it connected? Error: {e}")
            toast_error(
                toast_id=None,
                message="IMU Init Failed!",
                description="Failed to initialize IMU. Check connections.",
                cancel=None,
            )

    def read_data(self) -> ImuData | None:
        """Read IMU data synchronously."""
        if self.imu is None:
            return None
        try:
            return ImuData(
                acceleration=self.imu.get_acc_data().astype(np.float32),
                gyroscope=self.imu.get_gyr_data().astype(np.float32),
                temperature=self.imu.get_temp_data(),
            )
        except Exception as e:
            log_error(f"Error reading IMU data: {e}")
            return None

    async def read_loop(self) -> None:
        """Continuously read IMU data in a loop."""
        failure_count = 0
        while True:
            if not self.state.system_health.imu_ok:
                await asyncio.sleep(1)
                continue
            try:
                data = await asyncio.to_thread(self.read_data)
                if data:
                    self.state.imu = data
                    failure_count = 0
                else:
                    failure_count += 1
            except Exception as e:
                log_error(f"IMU read_loop error: {e}")
                failure_count += 1
            if failure_count >= SYSTEM_FAILURE_THRESHOLD:
                self.state.system_health.imu_ok = False
                failure_count = 0
                log_error("IMU failed 3 times, disabling IMU")
            await asyncio.sleep(1 / 100)
