from __future__ import annotations
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from rov_state import RovState

from websockets.server import WebSocketServerProtocol
from ..log import log_warn
from .receive.config import handle_get_config, handle_set_config
from .message import MessageType, WebsocketMessage
from ..models.config import RovConfig


async def handle_message(
    state: RovState,
    websocket: WebSocketServerProtocol,
    message: WebsocketMessage,
) -> None:
    try:
        payload = getattr(message, "payload", None)
        match message.type:
            case MessageType.GET_CONFIG:
                await handle_get_config(state, websocket)
            case MessageType.SET_CONFIG:
                await handle_set_config(state, websocket, cast(RovConfig, payload))
            case _:
                log_warn(f"Received unhandled message type: {message.type}")
    except Exception as exc:
        log_warn(f"Error in handler for message type '{message.type}': {exc}")
