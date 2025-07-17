import json
from log import log_info, log_error
from toast import toast_success
from typing import Any, Callable, Awaitable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import ROVState
    from rov_types import ROVConfig
    from websockets.server import WebSocketServerProtocol


async def handle_message(
    msg_type: str,
    payload: dict[str, object],
    websocket: "WebSocketServerProtocol",
    state: "ROVState",
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
    websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    msg = {"type": "config", "payload": state.rov_config}
    await websocket.send(json.dumps(msg))
    await log_info("Sent config to client.")


async def handle_set_config(
    payload: "ROVConfig",
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    state.set_config(payload)
    await log_info("Received and applied new config.")
    await toast_success(
        id=None,
        message="ROV config set successfully",
        description=None,
        cancel=None,
    )


import numpy as np
from numpy.typing import NDArray


async def handle_movement_command(
    payload: list[float],
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    # Convert payload (expected as list[float]) to numpy array for downstream operations
    payload_array: NDArray[np.float64] = np.array(payload, dtype=np.float64)
    state.thrusters.run_thrusters_with_regulator(payload_array)


async def handle_start_thruster_test(
    payload: int,
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    state.thrusters.test_thruster(payload)


async def handle_cancel_thruster_test(
    payload: int,
    _websocket: "WebSocketServerProtocol",
    _state: "ROVState",
) -> None:
    # Should call something in thrusters
    await log_info(f"Received command to cancel thruster test: {payload}")


async def handle_start_regulator_auto_tuning(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    _state: "ROVState",
) -> None:
    # Should call something in regulator
    await log_info("Received command to start regulator auto-tuning")


async def handle_cancel_regulator_auto_tuning(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    _state: "ROVState",
) -> None:
    # Should call something in regulator
    await log_info("Received command to cancel regulator auto-tuning")


async def handle_run_action_1(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    _state: "ROVState",
) -> None:
    # Should do an action of some  sort??
    return


async def handle_run_action_2(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    _state: "ROVState",
) -> None:
    # Should do an action of some  sort??
    return


async def handle_toggle_pitch_stabilization(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    state.pitch_stabilization = not state.pitch_stabilization


async def handle_toggle_roll_stabilization(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    state.roll_stabilization = not state.roll_stabilization


async def handle_toggle_depth_stabilization(
    _payload: None,
    _websocket: "WebSocketServerProtocol",
    state: "ROVState",
) -> None:
    state.depth_stabilization = not state.depth_stabilization


HandlerType = Callable[[Any, "WebSocketServerProtocol", "ROVState"], Awaitable[None]]

MESSAGE_TYPE_HANDLERS: Dict[str, HandlerType] = {
    "movementCommand": handle_movement_command,
    "getConfig": handle_get_config,
    "setConfig": handle_set_config,
    "startThrusterTest": handle_start_thruster_test,
    "cancelThrusterTest": handle_start_thruster_test,
    "startRegulatorAutoTuning": handle_start_regulator_auto_tuning,
    "cancelRegulatorAutoTuning": handle_cancel_regulator_auto_tuning,
    "runAction1": handle_run_action_1,
    "runAction2": handle_run_action_2,
    "togglePitchStabilization": handle_toggle_pitch_stabilization,
    "toggleRollStabilization": handle_toggle_roll_stabilization,
    "toggleDepthStabilization": handle_toggle_depth_stabilization,
}
