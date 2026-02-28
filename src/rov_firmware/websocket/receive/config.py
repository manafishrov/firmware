"""WebSocket config handlers for the ROV firmware."""

from websockets import ServerConnection

from ...log import log_info
from ...models.config import RovConfig
from ...rov_state import RovState
from ...toast import toast_success
from ..message import Config


async def handle_get_config(
    state: RovState,
    websocket: ServerConnection,
) -> None:
    """Handle get config request.

    Args:
        state: The ROV state.
        websocket: The WebSocket connection.
    """
    msg = Config(payload=state.rov_config).model_dump_json(by_alias=True)
    await websocket.send(msg)
    log_info("Sent config to client.")


async def handle_set_config(
    state: RovState,
    payload: RovConfig,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: The new ROV configuration.
    """
    state.rov_config = payload
    state.rov_config.save()
    log_info("Received and applied new config.")
    toast_success(
        toast_id=None,
        message="ROV config set successfully",
        description=None,
        cancel=None,
    )
