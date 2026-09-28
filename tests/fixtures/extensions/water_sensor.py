"""Background lifecycle test fixture; never bundled in the desktop app."""

import asyncio

from manafish_sdk import Context, Script, Widget


script = Script(
    "water_sensor",
    name="Water sensor (simulated)",
    description="Publishes a simulated leak status every second.",
)
wet = script.reading("wet", bool, name="Water detected", widget=Widget.WARNING)


@script.background(continue_on_disconnect=True)
async def background(_ctx: Context) -> None:
    """Publish samples for background lifecycle tests."""
    while True:
        await wet.publish(False)
        await asyncio.sleep(1)
