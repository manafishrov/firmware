"""WebSocket status send handlers for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from websockets import ServerConnection

    from rov_state import RovState

from ...models.rov_status import RovStatus
from ..message import StatusUpdate


async def handle_status_update(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    """Handle sending status update.

    Args:
        websocket: The WebSocket connection.
        state: The ROV state.
    """
    payload = RovStatus(
        pitch_stabilization=state.system_status.pitch_stabilization,
        roll_stabilization=state.system_status.roll_stabilization,
        depth_hold=state.system_status.depth_hold,
        battery_percentage=0,
    )
    message = StatusUpdate(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
