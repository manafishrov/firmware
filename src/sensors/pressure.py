"""Pressure sensor interface for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import SYSTEM_FAILURE_THRESHOLD


if TYPE_CHECKING:
    from rov_state import RovState

    from ..models.config import FluidType

import asyncio

from ms5837 import DENSITY_FRESHWATER, DENSITY_SALTWATER, MS5837_30BA

from ..log import log_error, log_info
from ..models.sensors import PressureData
from ..toast import toast_error


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
            self.state.system_health.pressure_sensor_ok = True
            log_info("MS5837 pressure sensor initialized successfully.")
        except Exception as e:
            self.state.system_health.pressure_sensor_ok = False
            log_error(
                f"Failed to initialize MS5837 pressure sensor. Is it connected? Error: {e}"
            )
            toast_error(
                toast_id=None,
                message="Pressure Sensor Init Failed!",
                description="Failed to initialize pressure sensor. Check connections.",
                cancel=None,
            )

    def _update_fluid_density(self) -> None:
        """Update the fluid density on the sensor based on current config."""
        if self.sensor is None:
            return
        if self.state.rov_config.fluid_type == FluidType.SALTWATER:
            self.sensor.setFluidDensity(DENSITY_SALTWATER)  # pyright: ignore[reportUnknownMemberType]
        else:
            self.sensor.setFluidDensity(DENSITY_FRESHWATER)  # pyright: ignore[reportUnknownMemberType]
        self.current_fluid_type = self.state.rov_config.fluid_type

    def read_data(self) -> PressureData | None:
        """Read pressure data from the sensor.

        Returns:
            PressureData if successful, None otherwise.
        """
        if self.sensor is None:
            return None
        try:
            if self.sensor.read():
                return PressureData(
                    pressure=self.sensor.pressure(),  # pyright: ignore[reportUnknownArgumentType]
                    temperature=self.sensor.temperature(),  # pyright: ignore[reportUnknownArgumentType]
                    depth=self.sensor.depth(),  # pyright: ignore[reportUnknownArgumentType]
                )
            else:
                return None
        except Exception as e:
            log_error(f"Error reading pressure sensor data: {e}")
            return None

    async def read_loop(self) -> None:
        """Continuously read pressure data in a loop."""
        failure_count = 0
        while True:
            if self.state.rov_config.fluid_type != self.current_fluid_type:
                self._update_fluid_density()
            if not self.state.system_health.pressure_sensor_ok:
                await asyncio.sleep(1)
                continue
            try:
                data = await asyncio.to_thread(self.read_data)
                if data:
                    self.state.pressure = data
                    failure_count = 0
                else:
                    failure_count += 1
            except Exception as e:
                log_error(f"Pressure sensor read_loop error: {e}")
                failure_count += 1
            if failure_count >= SYSTEM_FAILURE_THRESHOLD:
                self.state.system_health.pressure_sensor_ok = False
                failure_count = 0
                log_error("Pressure sensor failed 3 times, disabling pressure sensor")
            await asyncio.sleep(1 / 50)
