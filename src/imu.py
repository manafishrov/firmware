from __future__ import annotations
import asyncio
from log import log_error, log_info
from toast import toast_error
from bmi270.BMI270 import *
from typing import Optional
from rov_state import ROVState
from rov_types import IMUData


class IMU:
    def __init__(self, state: ROVState):
        self.state: ROVState = state
        self.imu: Optional[BMI270] = None

    async def initialize(self) -> None:
        try:
            await log_info("Attempting to initialize BMI270 IMU...")

            imu_instance = await asyncio.to_thread(BMI270(I2C_PRIM_ADDR))
            imu_instance.load_config_file()
            imu_instance.set_mode(PERFORMANCE_MODE)
            imu_instance.set_acc_range(ACC_RANGE_2G)
            imu_instance.set_gyr_range(GYR_RANGE_1000)
            imu_instance.set_acc_odr(ACC_ODR_100)
            imu_instance.set_gyr_odr(GYR_ODR_100)
            imu_instance.set_acc_bwp(ACC_BWP_NORMAL)
            imu_instance.set_gyr_bwp(GYR_BWP_NORMAL)
            imu_instance.disable_fifo_header()
            imu_instance.enable_data_streaming()
            imu_instance.enable_acc_filter_perf()
            imu_instance.enable_gyr_noise_perf()
            imu_instance.enable_gyr_filter_perf()

            self.imu = imu_instance
            await log_info("BMI270 IMU initialized successfully.")

        except Exception as e:
            await log_error(
                f"Failed to initialize BMI270 IMU. Is it connected? Error: {e}"
            )
            await toast_error(
                id=None,
                message="IMU Init Failed!",
                description="Failed to initialize IMU. Check connections.",
                cancel=None,
            )

    def _read_sensor_data_sync(self) -> Optional[IMUData]:
        try:
            if self.imu is None:
                return None
            return {
                "acceleration": self.imu.get_acc_data(),
                "gyroscope": self.imu.get_gyr_data(),
                "temperature": self.imu.get_temp_data(),
            }
        except Exception:
            return None

    async def start_reading_loop(self) -> None:
        READ_INTERVAL = 1 / 60

        while True:
            try:
                raw_data = await asyncio.to_thread(self._read_sensor_data_sync)

                if raw_data is not None:
                    self.state.imu["acceleration"] = raw_data["acceleration"]
                    self.state.imu["gyroscope"] = raw_data["gyroscope"]
                    self.state.imu["temperature"] = raw_data["temperature"]
                else:
                    await log_error(
                        "Failed to read IMU data in loop. Is the sensor still responsive?"
                    )
                    await toast_error(
                        id=None,
                        message="IMU Read Error!",
                        description="Cannot get data from IMU.",
                        cancel=None,
                    )

                await asyncio.sleep(READ_INTERVAL)

            except Exception as e:
                await log_error(f"Unhandled error in IMU reading loop: {e}")
                await asyncio.sleep(5)
