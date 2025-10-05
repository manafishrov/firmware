from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol

from ...models.config import RovConfig, FirmwareVersion
from ..message import Config, FirmwareVersion as FirmwareVersionMessage


async def handle_send_firmware_version(
    websocket: WebSocketServerProtocol, payload: FirmwareVersion
) -> None:
    message = FirmwareVersionMessage(payload=FirmwareVersion(version=payload)).json(
        by_alias=True
    )
    await websocket.send(message)


async def handle_send_config(
    websocket: WebSocketServerProtocol,
    payload: RovConfig,
) -> None:
    message = Config(payload=payload).json(by_alias=True)
    await websocket.send(message)

