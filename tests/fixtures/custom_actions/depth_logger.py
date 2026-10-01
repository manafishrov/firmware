"""CSV lifecycle test fixture; never bundled in the desktop app."""

import time

from manafish_sdk import Context, Script, Trigger


script = Script("depth_logger", name="Depth logger")


@script.action(
    name="Record depth",
    modes=(Trigger.ONCE, Trigger.HOLD, Trigger.TOGGLE),
    mode=Trigger.TOGGLE,
    interval_ms=1000,
)
async def record(ctx: Context) -> None:
    """Append timestamp and current depth once per scheduled invocation."""
    await ctx.log_csv([time.time(), ctx.rov.pressure.depth], "depth.csv")
