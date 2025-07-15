from typing import Any, Callable, Awaitable, Dict
from rov_types import ROVConfig
from websockets.server import WebSocketServerProtocol
from rov_state import ROVState
import json


async def handle_message(
    msg_type: str,
    payload: dict[str, object],
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    async def unknown_handler(payload, _websocket, _state):
        print(f"Unknown message type with payload: {payload}")

    handler = MESSAGE_TYPE_HANDLERS.get(msg_type, unknown_handler)
    try:
        await handler(payload, websocket, state)
    except Exception as exc:
        print(f"Error in handler for message type '{msg_type}': {exc}")


async def handle_get_config(
    _payload: None,
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    msg = {"type": "config", "payload": state.rov_config}
    await websocket.send(json.dumps(msg))


async def handle_set_config(
    payload: ROVConfig,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.set_config(payload)


async def handle_movement_command(
    payload: dict[str, object],
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    print(f"Received movement command: {payload}")


HandlerType = Callable[[Any, WebSocketServerProtocol, ROVState], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: Dict[str, HandlerType] = {
    "getConfig": handle_get_config,
    "setConfig": handle_set_config,
    "movementCommand": handle_movement_command,
}
