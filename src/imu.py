import asyncio
from rov_state import ROVState
from bmi270.BMI270 import *


class IMU:
    def __init__(self, state: ROVState):
        self.state = state
        self.imu = None

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
            return imu
        except Exception as e:
            # LOG + TOAST
            print(
                f"ERROR: Failed to initialize BMI270 IMU. Is it connected? Error: {e}"
            )
            return None

    def _read_sensor_data(self):
        try:
            acc = self.imu.get_acc_data()
            gyr = self.imu.get_gyr_data()
            temp = self.imu.get_temp_data()
            return {"acc": acc, "gyr": gyr, "temp": temp}
        except Exception as e:
            print(f"ERROR in reading IMU data: {e}")
            return None

    async def start_reading_loop(self):
        READ_INTERVAL = 1 / 60

        while True:
            try:
                raw_data = await asyncio.to_thread(self._read_sensor_data)
                if raw_data is not None:
                    self.state.imu["acc"] = raw_data["acc"]
                    self.state.imu["gyr"] = raw_data["gyr"]
                    self.state.imu["temp"] = raw_data["temp"]

                await asyncio.sleep(READ_INTERVAL)

            except Exception as e:
                print(f"ERROR in IMU reading loop: {e}")
                await asyncio.sleep(1)
