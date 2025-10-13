from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol
    from rov_state import RovState

from ...models.config import FirmwareVersion
from ..message import Config, FirmwareVersion as FirmwareVersionMessage
from ...constants import FIRMWARE_VERSION


async def handle_send_firmware_version(
    websocket: WebSocketServerProtocol,
) -> None:
    message = FirmwareVersionMessage(payload=FirmwareVersion(FIRMWARE_VERSION)).json(
        by_alias=True
    )
    await websocket.send(message)


async def handle_send_config(
    websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    message = Config(payload=state.rov_config).json(by_alias=True)
    await websocket.send(message)
