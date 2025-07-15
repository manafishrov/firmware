import asyncio
from typing import Optional
from rov_state import ROVState
from rov_types import IMUData
from bmi270.BMI270 import *


class IMU:
    def __init__(self, state: ROVState):
        self.state: ROVState = state
        self.imu: Optional[BMI270] = None

        try:
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
            self.imu = imu
        except Exception as e:
            # LOG + TOAST
            print(
                f"ERROR: Failed to initialize BMI270 IMU. Is it connected? Error: {e}"
            )
            self.imu = None

    def _read_sensor_data(self) -> Optional[IMUData]:
        try:
            if self.imu is None:
                return None
            return {
                "acceleration": self.imu.get_acc_data(),
                "gyroscope": self.imu.get_gyr_data(),
                "temperature": self.imu.get_temp_data(),
            }
        except Exception as e:
            print(f"ERROR in reading IMU data: {e}")
            return None

    async def start_reading_loop(self) -> None:
        READ_INTERVAL = 1 / 60

        while True:
            try:
                raw_data = await asyncio.to_thread(self._read_sensor_data)
                if raw_data is not None:
                    self.state.imu["acceleration"] = raw_data["acceleration"]
                    self.state.imu["gyroscope"] = raw_data["gyroscope"]
                    self.state.imu["temperature"] = raw_data["temperature"]

                await asyncio.sleep(READ_INTERVAL)

            except Exception as e:
                print(f"ERROR in IMU reading loop: {e}")
                await asyncio.sleep(1)
