"""WebSocket telemetry send handlers for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from websockets import ServerConnection

    from rov_state import RovState

from ...models.rov_telemetry import RovTelemetry
from ..message import Telemetry


async def handle_telemetry(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    payload = RovTelemetry(
        pitch=state.imu.pitch,
        roll=state.imu.roll,
        desired_pitch=state.regulator.desired_pitch,
        desired_roll=state.regulator.desired_roll,
        depth=state.pressure.depth,
        temperature=state.pressure.temperature,
        thruster_rpms=state.regulator.thruster_rpms,
    )
    message = Telemetry(payload=payload).json(by_alias=True)
    await websocket.send(message)
