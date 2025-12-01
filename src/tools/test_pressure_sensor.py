"""This script tests that the MS5837 pressure sensor is working correctly by reading and printing pressure, temperature, and depth data."""

import logging
import time

from ms5837 import DENSITY_FRESHWATER, MS5837_30BA


def main() -> None:
    """Run the pressure sensor test script."""
    logger = logging.getLogger(__name__)
    sensor = MS5837_30BA()
    sensor.setFluidDensity(DENSITY_FRESHWATER)  # pyright: ignore[reportUnknownMemberType]

    if not sensor.init():
        logger.error("Failed to initialize pressure sensor")
        return

    if not sensor.read():
        logger.error("Failed to read initial data from pressure sensor")
        return

    try:
        while True:
            if sensor.read():
                pressure = sensor.pressure()
                temperature = sensor.temperature()
                depth = sensor.depth()
                logger.info(
                    f"Pressure: {pressure} mbar, Temperature: {temperature} °C, Depth: {depth} m"
                )
            else:
                logger.error("Failed to read data from pressure sensor")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
