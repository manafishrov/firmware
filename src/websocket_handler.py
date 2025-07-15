from typing import Any, Callable, Awaitable, Dict
from rov_types import ROVConfig
from websockets.server import WebSocketServerProtocol
from rov_state import ROVState
import json
from log import log_info, log_error


async def handle_message(
    msg_type: str,
    payload: dict[str, object],
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    async def handle_unknown(payload, _websocket, _state):
        await log_error(
            f"Unknown message type received: {msg_type} with payload: {payload}"
        )

    handler = MESSAGE_TYPE_HANDLERS.get(msg_type, handle_unknown)
    try:
        await handler(payload, websocket, state)
    except Exception as exc:
        await log_error(f"Error in handler for message type '{msg_type}': {exc}")


async def handle_get_config(
    _payload: None,
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    msg = {"type": "config", "payload": state.rov_config}
    await websocket.send(json.dumps(msg))
    await log_info("Sent config to client.")


async def handle_set_config(
    payload: ROVConfig,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.set_config(payload)
    await log_info("Received and applied new config.")


async def handle_movement_command(
    payload: dict[str, object],
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    await log_info(f"Received movement command: {payload}")


HandlerType = Callable[[Any, WebSocketServerProtocol, ROVState], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: Dict[str, HandlerType] = {
    "getConfig": handle_get_config,
    "setConfig": handle_set_config,
    "movementCommand": handle_movement_command,
}
