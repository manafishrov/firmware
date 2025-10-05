from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

from websockets.server import WebSocketServerProtocol
from ..message import Config, Message
from ...log import log_info, log_error
from ...toast import toast_success
from ...models.config import RovConfig


async def handle_get_config(
    state: RovState,
    websocket: WebSocketServerProtocol,
    _message: Message,
) -> None:
    msg = Config(payload=state.rov_config).json(by_alias=True)
    await websocket.send(msg)
    log_info("Sent config to client.")


async def handle_set_config(
    state: RovState,
    _websocket: WebSocketServerProtocol,
    message: Message,
) -> None:
    try:
        new_config = RovConfig(**message.payload)
        state.rov_config = new_config
        state.rov_config.save()
        log_info("Received and applied new config.")
        toast_success(
            id=None,
            message="ROV config set successfully",
            description=None,
            cancel=None,
        )
    except Exception as e:
        log_error(f"Error setting config: {e}")
