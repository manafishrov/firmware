from __future__ import annotations
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_types import ROVConfig

import json
import time
from websockets.server import WebSocketServerProtocol
from log import log_info, log_error
from toast import toast_success
from rov_state import ROVState
from pico import flash_microcontroller_firmware


async def handle_message(
    msg_type: str,
    payload: dict[str, object],
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    async def handle_unknown(payload, _websocket, _state):
        log_error(
            f"Unknown message type received: {msg_type} with payload: {payload}"
        )

    handler = MESSAGE_TYPE_HANDLERS.get(msg_type, handle_unknown)
    try:
        await handler(payload, websocket, state)
    except Exception as exc:
        log_error(f"Error in handler for message type '{msg_type}': {exc}")


async def handle_get_config(
    _payload: None,
    websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    msg = {"type": "config", "payload": state.rov_config}
    await websocket.send(json.dumps(msg))
    log_info("Sent config to client.")


async def handle_set_config(
    payload: ROVConfig,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.set_config(payload)
    log_info("Received and applied new config.")
    toast_success(
        id=None,
        message="ROV config set successfully",
        description=None,
        cancel=None,
    )


async def handle_direction_vector(
    payload: list[float],
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    if isinstance(payload, list) and len(payload) <= 8:
        padded_payload = (payload + [0.0] * 8)[:8]
        state.thruster_command = padded_payload
        state.last_thruster_command_time = time.time()


async def handle_start_thruster_test(
    payload: int,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    log_info(f"Received command to start thruster test: {payload}")


async def handle_cancel_thruster_test(
    payload: int,
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    # Should call something in thrusters
    log_info(f"Received command to cancel thruster test: {payload}")


async def handle_start_regulator_auto_tuning(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    # Should call something in regulator
    log_info("Received command to start regulator auto-tuning")


async def handle_cancel_regulator_auto_tuning(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    # Should call something in regulator
    log_info("Received command to cancel regulator auto-tuning")


async def handle_custom_action(
    payload: str,
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    # Should do a custom action of some  sort??
    return


async def handle_toggle_pitch_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.pitch_stabilization = not state.pitch_stabilization


async def handle_toggle_roll_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.roll_stabilization = not state.roll_stabilization


async def handle_toggle_depth_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: ROVState,
) -> None:
    state.depth_stabilization = not state.depth_stabilization


async def handle_flash_microcontroller_firmware(
    payload: str,
    _websocket: WebSocketServerProtocol,
    _state: ROVState,
) -> None:
    flash_microcontroller_firmware(payload)


HandlerType = Callable[[Any, WebSocketServerProtocol, ROVState], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: dict[str, HandlerType] = {
    "directionVector": handle_direction_vector,
    "getConfig": handle_get_config,
    "setConfig": handle_set_config,
    "startThrusterTest": handle_start_thruster_test,
    "cancelThrusterTest": handle_cancel_thruster_test,
    "startRegulatorAutoTuning": handle_start_regulator_auto_tuning,
    "cancelRegulatorAutoTuning": handle_cancel_regulator_auto_tuning,
    "customAction": handle_custom_action,
    "togglePitchStabilization": handle_toggle_pitch_stabilization,
    "toggleRollStabilization": handle_toggle_roll_stabilization,
    "toggleDepthStabilization": handle_toggle_depth_stabilization,
    "flashMicrocontrollerFirmware": handle_flash_microcontroller_firmware,
}
