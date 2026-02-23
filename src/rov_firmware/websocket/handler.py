"""WebSocket message handler for the ROV firmware."""


from typing import cast

from websockets import ServerConnection

from ..log import log_warn
from ..models.actions import CustomAction, DirectionVector
from ..models.config import MicrocontrollerFirmwareVariant, RovConfig, ThrusterTest
from ..rov_state import RovState
from .message import WebsocketMessage
from .receive.actions import (
    handle_cancel_thruster_test,
    handle_custom_action,
    handle_direction_vector,
    handle_start_thruster_test,
)
from .receive.config import handle_get_config, handle_set_config
from .receive.microcontroller import handle_flash_microcontroller_firmware
from .receive.regulator import (
    handle_cancel_regulator_auto_tuning,
    handle_start_regulator_auto_tuning,
)
from .receive.state import (
    handle_toggle_auto_stabilization,
    handle_toggle_depth_hold,
)
from .types import MessageType


async def handle_message(  # noqa: C901
    state: RovState,
    websocket: ServerConnection,
    message: WebsocketMessage,
) -> None:
    """Handle a WebSocket message.

    Args:
        state: The ROV state.
        websocket: The WebSocket.
        message: The message.
    """
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
        case MessageType.TOGGLE_AUTO_STABILIZATION:
            await handle_toggle_auto_stabilization(state)
        case MessageType.TOGGLE_DEPTH_HOLD:
            await handle_toggle_depth_hold(state)
        case _:
            log_warn(f"Received unhandled message type: {message.type}")
