"""WebSocket config send handlers for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from websockets import ServerConnection

    from rov_state import RovState

from ...constants import FIRMWARE_VERSION
from ...models.config import FirmwareVersion
from ..message import Config, FirmwareVersion as FirmwareVersionMessage


async def handle_send_firmware_version(
    websocket: ServerConnection,
) -> None:
    message = FirmwareVersionMessage(payload=FirmwareVersion(FIRMWARE_VERSION)).json(
        by_alias=True
    )
    await websocket.send(message)


async def handle_send_config(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    message = Config(payload=state.rov_config).json(by_alias=True)
    await websocket.send(message)
