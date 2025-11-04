"""WebSocket telemetry send handlers for the ROV firmware."""

from __future__ import annotations

from websockets import ServerConnection

from ...constants import MAX_CURRENT_A, THRUSTER_POLES
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
    total_current_a = sum(state.esc.current_ca) / 100
    work_indicator_percentage = min(
        100, max(0, (total_current_a / MAX_CURRENT_A) * 100)
    )
    payload = RovTelemetry(
        pitch=state.regulator.pitch,
        roll=state.regulator.roll,
        desired_pitch=state.regulator.desired_pitch,
        desired_roll=state.regulator.desired_roll,
        thruster_rpms=[int(erpm / (THRUSTER_POLES // 2)) for erpm in state.esc.erpm],
        work_indicator_percentage=work_indicator_percentage,
    )
    message = Telemetry(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
