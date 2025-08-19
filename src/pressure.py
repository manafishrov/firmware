from __future__ import annotations
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from rov_state import ROVState
    from rov_types import PressureData

import asyncio
import ms5837
from log import log_error, log_info
from toast import toast_error


class PressureSensor:
    def __init__(self, state: ROVState):
        self.state: ROVState = state
        self.sensor: Optional[ms5837.MS5837_30BA] = None

    async def initialize(self) -> None:
        try:
            await log_info("Attempting to initialize MS5837 pressure sensor...")
            sensor_instance = await asyncio.to_thread(ms5837.MS5837_30BA)
            await asyncio.to_thread(sensor_instance.init)
            self.sensor = sensor_instance
            await log_info("MS5837 pressure sensor initialized successfully.")
        except Exception as e:
            await log_error(
                f"Failed to initialize MS5837 pressure sensor. Is it connected? Error: {e}"
            )
            await toast_error(
                id=None,
                message="Pressure Sensor Init Failed!",
                description="Failed to initialize pressure sensor. Check connections.",
                cancel=None,
            )

    def _read_sensor_data_sync(self) -> Optional[PressureData]:
        try:
            if self.sensor is None:
                return None

            if self.sensor.read():
                fluid_type = self.state.rov_config["fluidType"]
                if fluid_type == "saltwater":
                    depth = self.sensor.depth(ms5837.DENSITY_SALTWATER)
                else:
                    depth = self.sensor.depth(ms5837.DENSITY_FRESHWATER)
                return {
                    "pressure": self.sensor.pressure(),
                    "temperature": self.sensor.temperature(),
                    "depth": depth,
                }
            else:
                return None
        except Exception:
            return None

    async def start_reading_loop(self) -> None:
        READ_INTERVAL = 1 / 60

        while True:
            try:
                raw_data = await asyncio.to_thread(self._read_sensor_data_sync)
                if raw_data is not None:
                    self.state.pressure["pressure"] = raw_data["pressure"]
                    self.state.pressure["temperature"] = raw_data["temperature"]
                    self.state.pressure["depth"] = raw_data["depth"]
                else:
                    await log_error(
                        "Failed to read pressure data in loop. Is the sensor still responsive?"
                    )
                    await toast_error(
                        id=None,
                        message="Pressure Read Error!",
                        description="Cannot get data from pressure sensor.",
                        cancel=None,
                    )
                await asyncio.sleep(READ_INTERVAL)
            except Exception as e:
                await log_error(f"Unhandled error in pressure sensor reading loop: {e}")
                await asyncio.sleep(5)
