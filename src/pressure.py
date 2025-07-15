import asyncio
from typing import Optional
import ms5837
from rov_state import ROVState
from rov_types import PressureData


class PressureSensor:
    def __init__(self, state: ROVState):
        self.state: ROVState = state
        self.sensor: ms5837.MS5837_30BA = ms5837.MS5837_30BA()

        try:
            self.sensor.init()
        except Exception as e:
            print(
                f"ERROR: Failed to initialize MS5837 pressure sensor. Is it connected? Error: {e}"
            )

    def _read_sensor_data(self) -> Optional[PressureData]:
        try:
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
                print("ERROR: MS5837 sensor read failed!")
                return None
        except Exception as e:
            print(f"ERROR in reading MS5837 data: {e}")
            return None

    async def start_reading_loop(self) -> None:
        READ_INTERVAL = 1 / 60

        while True:
            try:
                raw_data = await asyncio.to_thread(self._read_sensor_data)
                if raw_data is not None:
                    self.state.pressure["pressure"] = raw_data["pressure"]
                    self.state.pressure["temperature"] = raw_data["temperature"]
                    self.state.pressure["depth"] = raw_data["depth"]
                await asyncio.sleep(READ_INTERVAL)
            except Exception as e:
                print(f"ERROR in pressure sensor reading loop: {e}")
                await asyncio.sleep(1)
