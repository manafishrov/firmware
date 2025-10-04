from __future__ import annotations
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

import time
from websockets.server import WebSocketServerProtocol
from ..log import log_info, log_error
from ..toast import toast_success
from ..pico import flash_microcontroller_firmware
from .message import ConfigMessage, MessageType
from ..models.config import RovConfig


async def handle_message(
    msg_type: str,
    payload: dict[str, object],
    websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    async def handle_unknown(payload, _websocket, _state):
        log_error(f"Unknown message type received: {msg_type} with payload: {payload}")

    handler = MESSAGE_TYPE_HANDLERS.get(msg_type, handle_unknown)
    try:
        await handler(payload, websocket, state)
    except Exception as exc:
        log_error(f"Error in handler for message type '{msg_type}': {exc}")


async def handle_get_config(
    _payload: None,
    websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    msg = ConfigMessage(payload=state.rov_config).json(by_alias=True)
    await websocket.send(msg)
    log_info("Sent config to client.")


async def handle_set_config(
    payload: dict,
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    try:
        new_config = RovConfig(**payload)
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


async def handle_direction_vector(
    payload: list[float],
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    if isinstance(payload, list) and len(payload) <= 8:
        padded_payload = (payload + [0.0] * 8)[:8]
        state.thruster_command = padded_payload
        state.last_thruster_command_time = time.time()


async def handle_start_thruster_test(
    payload: int,
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    log_info(f"Received command to start thruster test: {payload}")


async def handle_cancel_thruster_test(
    payload: int,
    _websocket: WebSocketServerProtocol,
    _state: RovState,
) -> None:
    # Should call something in thrusters
    log_info(f"Received command to cancel thruster test: {payload}")


async def handle_start_regulator_auto_tuning(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    _state: RovState,
) -> None:
    # Should call something in regulator
    log_info("Received command to start regulator auto-tuning")


async def handle_cancel_regulator_auto_tuning(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    _state: RovState,
) -> None:
    # Should call something in regulator
    log_info("Received command to cancel regulator auto-tuning")


async def handle_custom_action(
    payload: str,
    _websocket: WebSocketServerProtocol,
    _state: RovState,
) -> None:
    # Should do a custom action of some  sort??
    return


async def handle_toggle_pitch_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    state.system_status.pitch_stabilization = (
        not state.system_status.pitch_stabilization
    )


async def handle_toggle_roll_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    state.system_status.roll_stabilization = not state.system_status.roll_stabilization


async def handle_toggle_depth_stabilization(
    _payload: None,
    _websocket: WebSocketServerProtocol,
    state: RovState,
) -> None:
    state.system_status.depth_stabilization = (
        not state.system_status.depth_stabilization
    )


async def handle_flash_microcontroller_firmware(
    payload: str,
    _websocket: WebSocketServerProtocol,
    _state: RovState,
) -> None:
    flash_microcontroller_firmware(payload)


HandlerType = Callable[[Any, WebSocketServerProtocol, RovState], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: dict[str, HandlerType] = {
    MessageType.DIRECTION_VECTOR: handle_direction_vector,
    MessageType.GET_CONFIG: handle_get_config,
    MessageType.SET_CONFIG: handle_set_config,
    MessageType.START_THRUSTER_TEST: handle_start_thruster_test,
    MessageType.CANCEL_THRUSTER_TEST: handle_cancel_thruster_test,
    MessageType.START_REGULATOR_AUTO_TUNING: handle_start_regulator_auto_tuning,
    MessageType.CANCEL_REGULATOR_AUTO_TUNING: handle_cancel_regulator_auto_tuning,
    MessageType.CUSTOM_ACTION: handle_custom_action,
    MessageType.TOGGLE_PITCH_STABILIZATION: handle_toggle_pitch_stabilization,
    MessageType.TOGGLE_ROLL_STABILIZATION: handle_toggle_roll_stabilization,
    MessageType.TOGGLE_DEPTH_STABILIZATION: handle_toggle_depth_stabilization,
    MessageType.FLASH_MICROCONTROLLER_FIRMWARE: handle_flash_microcontroller_firmware,
}
