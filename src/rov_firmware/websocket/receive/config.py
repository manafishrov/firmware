"""WebSocket config handlers for the ROV firmware."""

from websockets import ServerConnection

from ...log import log_info
from ...models.config import PartialRovConfig, RovConfig
from ...rov_state import RovState
from ...toast import ToastContent, toast_success
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
    payload: PartialRovConfig,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: Partial ROV configuration update.
    """
    current_data = state.rov_config.model_dump(by_alias=False)
    update_data = payload.model_dump(exclude_none=True, by_alias=False)
    current_data.update(update_data)
    state.rov_config = RovConfig.model_validate(current_data)
    state.rov_config.save()
    log_info("Received and applied partial config update.")
    toast_success(
        identifier=None,
        content=ToastContent(
            message_key="toasts_rov_config_set_successfully",
        ),
        action=None,
    )
