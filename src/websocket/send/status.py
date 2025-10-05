from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol
    from rov_state import RovState

from ...models.rov_status import RovStatus
from ..message import StatusUpdate


async def handle_status_update(
    websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    payload = RovStatus(
        pitch_stabilization=state.system_status.pitch_stabilization,
        roll_stabilization=state.system_status.roll_stabilization,
        depth_stabilization=state.system_status.depth_stabilization,
        battery_percentage=0,
    )
    message = StatusUpdate(payload=payload).json(by_alias=True)
    await websocket.send(message)
