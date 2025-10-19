from __future__ import annotations
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from rov_state import RovState

from websockets.server import WebSocketServerProtocol
from ..log import log_warn
from .receive.config import handle_get_config, handle_set_config
from .receive.microcontroller import handle_flash_microcontroller_firmware
from .receive.actions import (
    handle_direction_vector,
    handle_start_thruster_test,
    handle_cancel_thruster_test,
    handle_custom_action,
)
from .receive.state import (
    handle_toggle_pitch_stabilization,
    handle_toggle_roll_stabilization,
    handle_toggle_depth_hold,
)
from .receive.regulator import (
    handle_start_regulator_auto_tuning,
    handle_cancel_regulator_auto_tuning,
)
from .message import MessageType, WebsocketMessage
from ..models.config import RovConfig, MicrocontrollerFirmwareVariant, ThrusterTest
from ..models.actions import DirectionVector, CustomAction


async def handle_message(
    state: RovState,
    websocket: WebSocketServerProtocol,
    message: WebsocketMessage,
) -> None:
    payload = getattr(message, "payload", None)
    match message.type:
        case MessageType.GET_CONFIG:
            await handle_get_config(state, websocket)
        case MessageType.SET_CONFIG:
            await handle_set_config(state, cast(RovConfig, payload))
        case MessageType.FLASH_MICROCONTROLLER_FIRMWARE:
            await handle_flash_microcontroller_firmware(
                cast(MicrocontrollerFirmwareVariant, payload)
            )
        case MessageType.DIRECTION_VECTOR:
            await handle_direction_vector(state, cast(DirectionVector, payload))
        case MessageType.START_THRUSTER_TEST:
            await handle_start_thruster_test(state, cast(ThrusterTest, payload))
        case MessageType.CANCEL_THRUSTER_TEST:
            await handle_cancel_thruster_test(state, cast(ThrusterTest, payload))
        case MessageType.START_REGULATOR_AUTO_TUNING:
            await handle_start_regulator_auto_tuning(state)
        case MessageType.CANCEL_REGULATOR_AUTO_TUNING:
            await handle_cancel_regulator_auto_tuning(state)
        case MessageType.CUSTOM_ACTION:
            await handle_custom_action(state, cast(CustomAction, payload))
        case MessageType.TOGGLE_PITCH_STABILIZATION:
            await handle_toggle_pitch_stabilization(state)
        case MessageType.TOGGLE_ROLL_STABILIZATION:
            await handle_toggle_roll_stabilization(state)
        case MessageType.TOGGLE_DEPTH_HOLD:
            await handle_toggle_depth_hold(state)
        case _:
            log_warn(f"Received unhandled message type: {message.type}")
