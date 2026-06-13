"""Custom action that reports a water sensor's state as a toast.

Wiring (3-pin water sensor, S / + / -):
    -  -> Pi pin 6  (GND)
    +  -> Pi pin 1  (3V3)
    S  -> Pi pin 11 (GPIO17)

The sensor's signal pin reads HIGH when its traces are bridged by water and
LOW when dry. Change ``WATER_SENSOR_GPIO_PIN`` below if you wire S elsewhere.
"""

import asyncio

from gpiozero import DigitalInputDevice

from ..log import log_error, log_info
from ..rov_state import RovState
from ..toast import ToastContent, toast_error, toast_info, toast_warn


# BCM pin number for the sensor's S (signal) line.
WATER_SENSOR_GPIO_PIN = 17


def _read_water_sensor() -> bool:
    """Return True if water is detected, False if dry.

    Opens the GPIO line for a single read and releases it again so the pin is
    not held by this one-shot action.
    """
    sensor = DigitalInputDevice(WATER_SENSOR_GPIO_PIN)
    try:
        return bool(sensor.value)
    finally:
        sensor.close()


async def execute(_state: RovState) -> None:
    """Read the water sensor and show its state in a toast."""
    log_info("Executing water sensor custom action")

    try:
        water_detected = await asyncio.to_thread(_read_water_sensor)
    except Exception as e:
        log_error(f"Failed to read water sensor: {e}")
        toast_error(
            identifier=None,
            content=ToastContent(
                message_key="toasts_water_sensor_read_failed",
                description_key="toasts_water_sensor_read_failed_description",
            ),
            action=None,
        )
        return

    if water_detected:
        toast_warn(
            identifier=None,
            content=ToastContent(
                message_key="toasts_water_sensor_wet_title",
                description_key="toasts_water_sensor_wet_description",
            ),
            action=None,
        )
    else:
        toast_info(
            identifier=None,
            content=ToastContent(
                message_key="toasts_water_sensor_dry_title",
                description_key="toasts_water_sensor_dry_description",
            ),
            action=None,
        )
