"""This script tests that the SMP2000 pressure sensor is working correctly by reading and printing pressure, temperature, and depth data."""

import logging
import time

from rov_firmware.constants import (
    DENSITY_FRESHWATER,
    GRAVITY,
    PASCAL_PER_KILOPASCAL,
    SMP2000_PRESSURE_MAX_KPA,
    SMP2000_PRESSURE_MIN_KPA,
    SMP2000_SPAN_MAX_COUNTS,
    SMP2000_SPAN_MIN_COUNTS,
    SURFACE_PRESSURE_CAPTURE_SAMPLES,
)
from rov_firmware.sensors.smp2000 import Smp2000, Smp2000Calibration


READ_INTERVAL_SECONDS = 0.1


def main() -> None:
    """Run the pressure sensor test script."""
    logger = logging.getLogger(__name__)
    sensor = Smp2000(
        Smp2000Calibration(
            pressure_min_kpa=SMP2000_PRESSURE_MIN_KPA,
            pressure_max_kpa=SMP2000_PRESSURE_MAX_KPA,
            span_min_counts=SMP2000_SPAN_MIN_COUNTS,
            span_max_counts=SMP2000_SPAN_MAX_COUNTS,
        )
    )

    try:
        sensor.open()
    except Exception as e:
        logger.error(f"Failed to initialize pressure sensor: {e}")
        return

    frame = sensor.read_frame()
    logger.info(f"Status field: {frame.status} (0 = valid, 1 = stale, 3 = fault)")
    logger.info(f"Raw pressure counts: {frame.pressure_counts}")
    logger.info(f"Slowest cycle: {sensor.measure_conversion_time() * 1000:.1f} ms")
    logger.info(
        f"Calibrated for {SMP2000_PRESSURE_MIN_KPA:.0f}-{SMP2000_PRESSURE_MAX_KPA:.0f} kPa "
        f"across counts {SMP2000_SPAN_MIN_COUNTS}-{SMP2000_SPAN_MAX_COUNTS}"
    )

    # Zero depth at the pressure where the tool starts, as the firmware does.
    surface_kpa = sensor.measure_average(SURFACE_PRESSURE_CAPTURE_SAMPLES)
    if surface_kpa is None:
        logger.error("Could not capture a surface reference pressure")
        sensor.close()
        return
    logger.info(f"Surface reference: {surface_kpa:.3f} kPa")

    try:
        while True:
            measurement = sensor.measure()
            if measurement is None:
                logger.error("Sensor did not return a valid frame")
                break
            # Repeated reads return the last completed conversion, so this is
            # the frame behind the measurement above.
            frame = sensor.read_frame()
            depth = (
                (measurement.pressure_kpa - surface_kpa) * PASCAL_PER_KILOPASCAL
            ) / (DENSITY_FRESHWATER * GRAVITY)
            logger.info(
                f"Counts: {frame.pressure_counts:8d}  "
                f"Pressure: {measurement.pressure_kpa:8.3f} kPa  "
                f"Temperature: {measurement.temperature_c:6.2f} °C  "
                f"Depth: {depth:7.3f} m (freshwater)"
            )
            time.sleep(READ_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()
