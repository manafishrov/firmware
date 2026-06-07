"""Custom action that reports the Pi's CPU temperature as a toast."""

import asyncio

import psutil

from ..log import log_error, log_info
from ..rov_state import RovState
from ..toast import ToastContent, toast_error, toast_info


def _read_cpu_temperature() -> float | None:
    """Read the CPU temperature in degrees Celsius, or None if unavailable."""
    try:
        readings = psutil.sensors_temperatures().get("cpu_thermal")  # ty: ignore[possibly-missing-attribute]
    except Exception as e:
        log_error(f"CPU temperature read failed: {e}")
        return None

    return readings[0].current if readings else None


async def execute(_state: RovState) -> None:
    """Read the Pi CPU temperature and show it in a toast."""
    log_info("Executing CPU temperature custom action")
    temperature = await asyncio.to_thread(_read_cpu_temperature)

    if temperature is None:
        toast_error(
            identifier=None,
            content=ToastContent(
                message_key="toasts_cpu_temperature_unavailable",
                description_key="toasts_cpu_temperature_unavailable_description",
            ),
            action=None,
        )
        return

    toast_info(
        identifier=None,
        content=ToastContent(
            message_key="toasts_cpu_temperature_title",
            message_args={"temperature": round(temperature, 1)},
        ),
        action=None,
    )
