from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol
    from rov_state import RovState

from ...models.rov_status import RovStatus
from ..message import StatusUpdate


async def handle_status_update(
    state: RovState,
    websocket: WebSocketServerProtocol,
    payload: RovStatus,
) -> None:
    message = StatusUpdate(payload=payload).json(by_alias=True)
    await websocket.send(message)
