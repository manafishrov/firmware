"""Pressure sensor interface for the ROV firmware."""

import asyncio
import math
import time

from ms5837 import DENSITY_FRESHWATER, DENSITY_SALTWATER, MS5837_30BA

from ..constants import (
    DEPTH_DERIVATIVE_EMA_TAU,
    PRESSURE_SENSOR_READ_FREQUENCY,
    SYSTEM_FAILURE_THRESHOLD,
)
from ..log import log_error, log_info
from ..models.config import FluidType
from ..models.sensors import PressureData
from ..rov_state import RovState
from ..toast import ToastContent, toast_error


class PressureSensor:
    """Pressure sensor class."""

    def __init__(self, state: RovState):
        """Initialize the pressure sensor.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.sensor: MS5837_30BA | None = None
        self.current_fluid_type: FluidType | None = None

    async def initialize(self) -> None:
        """Asynchronously initialize the pressure sensor."""
        try:
            log_info("Attempting to initialize MS5837 pressure sensor...")
            sensor_instance = await asyncio.to_thread(MS5837_30BA)
            _ = await asyncio.to_thread(sensor_instance.init)
            self.sensor = sensor_instance
            self._update_fluid_density()
            self.state.system_health.pressure_sensor_healthy = True
            log_info("MS5837 pressure sensor initialized successfully.")
        except Exception as e:
            self.state.system_health.pressure_sensor_healthy = False
            log_error(
                f"Failed to initialize MS5837 pressure sensor. Is it connected? Error: {e}"
            )
            toast_error(
                identifier=None,
                content=ToastContent(
                    message_key="toasts_pressure_sensor_init_failed",
                    description_key="toasts_pressure_sensor_init_failed_description",
                ),
                action=None,
            )

    def _update_fluid_density(self) -> None:
        """Update the fluid density on the sensor based on current config."""
        if self.sensor is None:
            return
        if self.state.rov_config.fluid_type == FluidType.SALTWATER:
            self.sensor.setFluidDensity(DENSITY_SALTWATER)
        else:
            self.sensor.setFluidDensity(DENSITY_FRESHWATER)
        self.current_fluid_type = self.state.rov_config.fluid_type

    def read_data(self) -> PressureData | None:
        """Read pressure data from the sensor.

        Reads pressure, temperature, and depth from the MS5837 sensor. Units are pressure
        in mbar, temperature in °C, and depth in meters (calculated using configured fluid
        density).

        Returns:
            PressureData if successful (containing pressure in mbar, temperature in °C,
            depth in m), None otherwise.
        """
        if self.sensor is None:
            return None
        try:
            if self.sensor.read():
                return PressureData(
                    pressure=self.sensor.pressure(),
                    temperature=self.sensor.temperature(),
                    depth=self.sensor.depth(),
                )
            else:
                return None
        except Exception as e:
            log_error(f"Error reading pressure sensor data: {e}")
            return None

    def _blocking_read_loop(self) -> None:
        """Pressure sensor read loop running in a dedicated background thread.

        Runs entirely outside the asyncio event loop so the read rate is not
        affected by event-loop callback latency. State writes are safe without
        a lock because CPython's GIL makes single object-reference assignments atomic.
        """
        failure_count = 0
        interval = 1.0 / PRESSURE_SENSOR_READ_FREQUENCY
        next_tick = time.perf_counter() + interval
        previous_depth: float = 0.0
        filtered_depth_change: float = 0.0
        previous_read_time: float = 0.0
        while True:
            if self.state.rov_config.fluid_type != self.current_fluid_type:
                self._update_fluid_density()
            if not self.state.system_health.pressure_sensor_healthy:
                time.sleep(1)
                next_tick = time.perf_counter() + interval
                previous_read_time = 0.0
                failure_count = 0
                continue
            try:
                data = self.read_data()
                if data:
                    now = time.time()
                    if previous_read_time > 0.0:
                        dt = now - previous_read_time
                        raw_depth_change = (data.depth - previous_depth) / dt
                        alpha = math.exp(-dt / DEPTH_DERIVATIVE_EMA_TAU)
                        filtered_depth_change = (
                            alpha * filtered_depth_change
                            + (1.0 - alpha) * raw_depth_change
                        )
                    previous_depth = data.depth
                    previous_read_time = now
                    data.depth_change = filtered_depth_change
                    self.state.pressure = data
                    failure_count = 0
                else:
                    failure_count += 1
            except Exception as e:
                log_error(f"Pressure sensor read_loop error: {e}")
                failure_count += 1
            if failure_count >= SYSTEM_FAILURE_THRESHOLD:
                self.state.system_health.pressure_sensor_healthy = False
                failure_count = 0
                log_error("Pressure sensor failed 3 times, disabling pressure sensor")
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_tick += interval
            now = time.perf_counter()
            if next_tick < now:
                next_tick = now + interval

    async def read_loop(self) -> None:
        """Run the pressure sensor read loop in a dedicated background thread."""
        await asyncio.to_thread(self._blocking_read_loop)
