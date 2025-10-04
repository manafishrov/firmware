from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

from bmi270.BMI270 import *
import asyncio
from ..log import log_error, log_info
from ..toast import toast_error
from ..models.sensors import ImuData


class Imu:
    def __init__(self, state: RovState):
        self.state: RovState = state
        self.imu: Optional[BMI270] = None

    async def initialize(self) -> None:
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
                id=None,
                message="IMU Init Failed!",
                description="Failed to initialize IMU. Check connections.",
                cancel=None,
            )

    def read_data(self) -> Optional[ImuData]:
        try:
            if not self.state.system_health.imu_ok:
                return None
            return ImuData(
                acceleration=self.imu.get_acc_data(),
                gyroscope=self.imu.get_gyr_data(),
                temperature=self.imu.get_temp_data(),
            )
        except Exception as e:
            log_error(f"Error reading IMU data: {e}")
            return None
