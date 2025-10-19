from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

import asyncio
import ms5837
from ..log import log_error, log_info
from ..toast import toast_error
from ..models.sensors import PressureData


class PressureSensor:
    def __init__(self, state: RovState):
        self.state: RovState = state
        self.sensor: Optional[ms5837.MS5837_30BA] = None

    async def initialize(self) -> None:
        try:
            log_info("Attempting to initialize MS5837 pressure sensor...")
            sensor_instance = await asyncio.to_thread(ms5837.MS5837_30BA)
            await asyncio.to_thread(sensor_instance.init)
            self.sensor = sensor_instance
            self.state.system_health.pressure_sensor_ok = True
            log_info("MS5837 pressure sensor initialized successfully.")
        except Exception as e:
            self.state.system_health.pressure_sensor_ok = False
            log_error(
                f"Failed to initialize MS5837 pressure sensor. Is it connected? Error: {e}"
            )
            toast_error(
                id=None,
                message="Pressure Sensor Init Failed!",
                description="Failed to initialize pressure sensor. Check connections.",
                cancel=None,
            )

    def read_data(self) -> Optional[PressureData]:
        try:
            if self.sensor.read():
                if self.state.rov_config.fluid_type == "saltwater":
                    depth = self.sensor.depth(ms5837.DENSITY_SALTWATER)
                else:
                    depth = self.sensor.depth(ms5837.DENSITY_FRESHWATER)
                return PressureData(
                    pressure=self.sensor.pressure(),
                    temperature=self.sensor.temperature(),
                    depth=depth,
                )
            else:
                return None
        except Exception as e:
            log_error(f"Error reading pressure sensor data: {e}")
            return None

    async def read_loop(self) -> None:
        failure_count = 0
        while True:
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
            if failure_count >= 3:
                self.state.system_health.pressure_sensor_ok = False
                failure_count = 0
                log_error("Pressure sensor failed 3 times, disabling pressure sensor")
            await asyncio.sleep(1 / 50)
