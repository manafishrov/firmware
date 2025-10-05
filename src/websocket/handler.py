from __future__ import annotations
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

from websockets.server import WebSocketServerProtocol
from ..log import log_error
from .receive.config import handle_get_config, handle_set_config
from .message import MessageType, WebsocketMessage


async def handle_message(
    state: RovState,
    websocket: WebSocketServerProtocol,
    message: WebsocketMessage,
) -> None:
    async def handle_unknown(
        _state: RovState, _websocket: WebSocketServerProtocol, payload: Any
    ) -> None:
        log_error(f"Unknown message type received with payload: {payload}")

    handler = MESSAGE_TYPE_HANDLERS.get(message.type, handle_unknown)
    try:
        payload = getattr(message, "payload", None)
        await handler(state, websocket, payload)
    except Exception as exc:
        log_error(f"Error in handler for message type '{message.type}': {exc}")


HandlerType = Callable[[RovState, WebSocketServerProtocol, Any], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: dict[str, HandlerType] = {
    MessageType.GET_CONFIG: handle_get_config,
    MessageType.SET_CONFIG: handle_set_config,
}
