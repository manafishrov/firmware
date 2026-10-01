"""Action lifecycle test fixture; never bundled in the desktop app."""

from pydantic import BaseModel

from manafish_sdk import Context, Script


script = Script("dispenser", name="Dispenser (simulated)")
count = script.reading("count", float, name="Dispensed")


class DispenserState(BaseModel):
    calls: int = 0


state = DispenserState()


@script.action(name="Dispense")
async def dispense(ctx: Context) -> None:  # noqa: ARG001 - injected by lifecycle tests
    """Count calls without operating hardware."""
    state.calls += 1
    await count.publish(state.calls)
