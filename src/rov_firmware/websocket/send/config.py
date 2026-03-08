"""WebSocket config send handlers for the ROV firmware."""

from websockets import ServerConnection

from ...rov_state import RovState
from ..message import Config


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
