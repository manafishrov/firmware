"""WebSocket config send handlers for the ROV firmware."""

from websockets import ServerConnection

from ...constants import FIRMWARE_VERSION
from ...models.config import FirmwareVersion
from ...rov_state import RovState
from ..message import Config, FirmwareVersion as FirmwareVersionMessage


async def handle_send_firmware_version(
    websocket: ServerConnection,
) -> None:
    """Handle sending firmware version.

    Args:
        websocket: The WebSocket connection.
    """
    message = FirmwareVersionMessage(
        payload=FirmwareVersion(FIRMWARE_VERSION)
    ).model_dump_json(by_alias=True)
    await websocket.send(message)


async def handle_send_config(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    """Handle sending ROV config.

    Args:
        websocket: The WebSocket connection.
        state: The ROV state.
    """
    message = Config(payload=state.rov_config).model_dump_json(by_alias=True)
    await websocket.send(message)
