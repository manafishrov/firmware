"""WebSocket telemetry send handlers for the ROV firmware."""

from __future__ import annotations

from websockets import ServerConnection

from ...constants import THRUSTER_POLES
from ...models.rov_telemetry import RovTelemetry
from ...rov_state import RovState
from ..message import Telemetry


async def handle_telemetry(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    """Handle sending telemetry data.

    Args:
        websocket: The WebSocket connection.
        state: The ROV state.
    """
    payload = RovTelemetry(
        pitch=state.regulator.pitch,
        roll=state.regulator.roll,
        desired_pitch=state.regulator.desired_pitch,
        desired_roll=state.regulator.desired_roll,
        depth=state.pressure.depth,
        temperature=state.pressure.temperature,
        thruster_rpms=[int(erpm / (THRUSTER_POLES // 2)) for erpm in state.esc.erpm],
    )
    message = Telemetry(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
