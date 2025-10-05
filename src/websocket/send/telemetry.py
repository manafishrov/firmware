from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol
    from rov_state import RovState

from ...models.rov_telemetry import RovTelemetry
from ..message import Telemetry


async def handle_telemetry(
    state: RovState,
    websocket: WebSocketServerProtocol,
    payload: RovTelemetry,
) -> None:
    message = Telemetry(payload=payload).json(by_alias=True)
    await websocket.send(message)
