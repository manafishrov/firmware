"""IMU sensor interface for the ROV firmware."""

import asyncio
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
import numpy as np

from ..constants import IMU_READ_FREQUENCY, SYSTEM_FAILURE_THRESHOLD
from ..log import log_error, log_info
from ..models.sensors import ImuData
from ..rov_state import RovState
from ..toast import ToastContent, toast_error, toast_info


class Imu:
    """IMU sensor class."""

    def __init__(self, state: RovState):
        """Initialize the IMU sensor.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.imu: BMI270 | None = None
        self._read_rate_counter: int = 0
        self._read_rate_window_start: float = 0.0

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
            self.state.system_health.imu_healthy = True
            log_info("BMI270 IMU initialized successfully.")

        except Exception as e:
            self.state.system_health.imu_healthy = False
            log_error(f"Failed to initialize BMI270 IMU. Is it connected? Error: {e}")
            toast_error(
                identifier=None,
                content=ToastContent(
                    message_key="toasts_imu_init_failed",
                    description_key="toasts_imu_init_failed_description",
                ),
                action=None,
            )

    def read_data(self) -> ImuData | None:
        """Read the current IMU sample and return sensor measurements in NED coordinates.

        Reads accelerometer, gyroscope, and temperature from the BMI270. The BMI270 library
        automatically converts raw data to SI units (accel in m/s², gyro in rad/s). Applies
        ENU to NED axis convention transform. Returns None if the IMU is not initialized or
        a read error occurs.

        Returns:
            ImuData | None: An ImuData instance containing `acceleration` (m/s²), `gyroscope`
            (rad/s), and `temperature` (°C) on success; `None` if the device is uninitialized
            or a read fails.
        """
        if self.imu is None:
            return None
        try:
            accel = self.imu.get_acc_data().astype(np.float32)
            gyr = self.imu.get_gyr_data().astype(np.float32)

            # Change convention from ENU to NED
            accel *= np.array([1.0, -1.0, -1.0], dtype=np.float32)
            gyr *= np.array([1.0, -1.0, -1.0], dtype=np.float32)

            return ImuData(
                acceleration=accel,
                gyroscope=gyr,
                temperature=self.imu.get_temp_data(),
            )
        except Exception as e:
            log_error(f"Error reading IMU data: {e}")
            return None

    def _blocking_read_loop(self) -> None:
        """IMU read loop running in a dedicated background thread.

        Runs entirely outside the asyncio event loop so the read rate is
        determined by OS thread scheduling, not by event-loop callback latency.
        State writes (self.state.imu = data) are safe without a lock because
        CPython's GIL makes single object-reference assignments atomic.
        """
        failure_count = 0
        interval = 1.0 / IMU_READ_FREQUENCY
        next_tick = time.perf_counter() + interval
        while True:
            if not self.state.system_health.imu_healthy:
                time.sleep(1)
                next_tick = time.perf_counter() + interval
                failure_count = 0
                continue
            try:
                data = self.read_data()
                if data:
                    self.state.imu = data
                    failure_count = 0
                    now = time.time()
                    self._read_rate_counter += 1
                    if self._read_rate_window_start == 0.0:
                        self._read_rate_window_start = now
                    elif now - self._read_rate_window_start >= 1.0:
                        elapsed = now - self._read_rate_window_start
                        hz = round(self._read_rate_counter / elapsed)
                        toast_info(
                            "imu_read_rate",
                            ToastContent(
                                message_key="toasts_recording_saved_path",
                                message_args={"path": f"IMU read loop: {hz} Hz"},
                            ),
                            None,
                        )
                        self._read_rate_counter = 0
                        self._read_rate_window_start = now
                else:
                    failure_count += 1
            except Exception as e:
                log_error(f"IMU read_loop error: {e}")
                failure_count += 1
            if failure_count >= SYSTEM_FAILURE_THRESHOLD:
                self.state.system_health.imu_healthy = False
                failure_count = 0
                log_error("IMU failed 3 times, disabling IMU")
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_tick += interval
            now = time.perf_counter()
            if next_tick < now:
                next_tick = now + interval

    async def read_loop(self) -> None:
        """Run the IMU read loop in a dedicated background thread."""
        await asyncio.to_thread(self._blocking_read_loop)
