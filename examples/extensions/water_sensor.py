"""Continuously monitor the original active-high water sensor on GPIO17.

Wiring (S / + / -): S -> Pi pin 11 (GPIO17), + -> pin 1 (3V3), - -> pin 6 (GND).
Save and enable this script in Custom actions; disable it to stop monitoring.
Add "Water detected" in Appearance. Bind "Toggle monitoring" to an action widget
or keyboard/controller button to pause/resume. Pausing is temporary: monitoring
starts again after an app disconnect, script reload, or ROV restart while enabled. Change WATER_SENSOR_GPIO_PIN
if the signal is wired to a different BCM pin.
"""

import asyncio
from typing import ClassVar

from gpiozero import DigitalInputDevice
from pydantic import BaseModel, ConfigDict

from manafish_sdk import Context, NotificationLevel, Script, Widget


WATER_SENSOR_GPIO_PIN = 17
SAMPLE_INTERVAL_SECONDS = 0.25

script = Script(
    "water_sensor",
    name="Water sensor",
    description="Continuously monitor the GPIO17 water sensor for water.",
)
wet = script.reading(
    "wet", bool, name="Water detected", widget=Widget.WARNING, stale_after=2.0
)


class SensorState(BaseModel):
    """Remember the previous result to avoid repeating notifications."""

    model_config: ClassVar[ConfigDict] = ConfigDict(validate_assignment=True)

    monitoring_enabled: bool = True
    last_wet: bool | None = None


sensor_state = SensorState()
# Serialize toggles and reads so an in-flight result cannot overwrite a pause.
sensor_lock = asyncio.Lock()


def _read_water_sensor() -> bool:
    """Release the GPIO line after each read, including failed reads."""
    sensor = DigitalInputDevice(WATER_SENSOR_GPIO_PIN)
    try:
        return bool(sensor.value)
    finally:
        sensor.close()


async def sample(ctx: Context) -> None:
    """Publish every reading and notify on the first result or a state change."""
    try:
        read = asyncio.create_task(asyncio.to_thread(_read_water_sensor))
        try:
            water_detected = await asyncio.shield(read)
        except asyncio.CancelledError:
            # Let the GPIO thread release its pin before disabling or replacing us.
            await read
            raise
    except Exception as error:
        await wet.publish(None)
        await ctx.notify(
            "Could not read the water sensor",
            level=NotificationLevel.ERROR,
            description="Check the sensor wiring.",
            key="status",
        )
        msg = f"Failed to read water sensor: {error}"
        raise RuntimeError(msg) from error

    await wet.publish(water_detected)
    if sensor_state.last_wet != water_detected:
        sensor_state.last_wet = water_detected
        await ctx.notify(
            "Water detected" if water_detected else "Water sensor dry",
            level=NotificationLevel.WARNING
            if water_detected
            else NotificationLevel.INFO,
            key="status",
        )


@script.action(name="Toggle monitoring")
async def toggle_monitoring(ctx: Context) -> None:
    """Pause/resume once per press; the background task owns the sampling loop."""
    async with sensor_lock:
        sensor_state.monitoring_enabled = not sensor_state.monitoring_enabled
        sensor_state.last_wet = None
        if not sensor_state.monitoring_enabled:
            await wet.publish(None)
        await ctx.notify(
            "Water sensor monitoring resumed"
            if sensor_state.monitoring_enabled
            else "Water sensor monitoring paused",
            key="status",
        )


@script.background(continue_on_disconnect=True)
async def monitor(ctx: Context) -> None:
    """Start on enable and yield between samples so other firmware keeps running."""
    while True:
        async with sensor_lock:
            if sensor_state.monitoring_enabled:
                await sample(ctx)
        await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
