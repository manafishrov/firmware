"""WebSocket message handler for the ROV firmware."""

from typing import Any, cast

from ..esc_firmware import flash_esc_firmware
from ..log import log_warn
from ..models.actions import CustomAction, DirectionVector
from ..models.config import (
    McuBoard,
    PartialRovConfig,
    ThrusterTest,
)
from ..rov_state import RovState
from ..serial import SerialManager
from .message import WebsocketMessage
from .receive.actions import (
    handle_cancel_thruster_test,
    handle_custom_action,
    handle_direction_vector,
    handle_start_thruster_test,
)
from .receive.config import handle_get_config, handle_import_config, handle_set_config
from .receive.mcu import handle_flash_mcu_firmware
from .receive.regulator import (
    handle_cancel_regulator_auto_tuning,
    handle_set_desired_depth,
    handle_start_regulator_auto_tuning,
)
from .receive.state import (
    handle_set_auto_stabilization,
    handle_set_depth_hold,
    handle_toggle_auto_stabilization,
    handle_toggle_depth_hold,
)
from .types import MessageType


async def _handle_state_payload_message(
    state: RovState,
    payload: object,
    message_type: MessageType,
) -> bool:
    match message_type:
        case MessageType.SET_AUTO_STABILIZATION:
            await handle_set_auto_stabilization(state, cast(bool, payload))
        case MessageType.SET_DEPTH_HOLD:
            await handle_set_depth_hold(state, cast(bool, payload))
        case _:
            return False

    return True


async def _handle_payload_message(
    state: RovState,
    payload: object,
    message: WebsocketMessage,
) -> bool:
    match message.type:
        case MessageType.SET_CONFIG:
            await handle_set_config(state, cast(PartialRovConfig, payload))
        case MessageType.IMPORT_CONFIG:
            await handle_import_config(state, cast(dict[str, Any], payload))
        case MessageType.FLASH_MCU_FIRMWARE:
            await handle_flash_mcu_firmware(state, cast(McuBoard, payload))
        case MessageType.DIRECTION_VECTOR:
            await handle_direction_vector(state, cast(DirectionVector, payload))
        case MessageType.START_THRUSTER_TEST:
            await handle_start_thruster_test(state, cast(ThrusterTest, payload))
        case MessageType.CANCEL_THRUSTER_TEST:
            await handle_cancel_thruster_test(state, cast(ThrusterTest, payload))
        case MessageType.CUSTOM_ACTION:
            await handle_custom_action(state, cast(CustomAction, payload))
        case MessageType.SET_DESIRED_DEPTH:
            await handle_set_desired_depth(state, cast(float, payload))
        case _:
            return await _handle_state_payload_message(state, payload, message.type)

    return True


async def handle_message(
    state: RovState,
    serial_manager: SerialManager,
    message: WebsocketMessage,
) -> None:
    """Handle a WebSocket message.

    Args:
        state: The ROV state.
        serial_manager: The MCU serial connection used for ESC updates.
        message: The message.
    """
    payload = getattr(message, "payload", None)
    match message.type:
        case MessageType.GET_CONFIG:
            await handle_get_config(state)
        case MessageType.START_REGULATOR_AUTO_TUNING:
            await handle_start_regulator_auto_tuning(state)
        case MessageType.CANCEL_REGULATOR_AUTO_TUNING:
            await handle_cancel_regulator_auto_tuning(state)
        case MessageType.TOGGLE_AUTO_STABILIZATION:
            await handle_toggle_auto_stabilization(state)
        case MessageType.TOGGLE_DEPTH_HOLD:
            await handle_toggle_depth_hold(state)
        case MessageType.FLASH_ESC_FIRMWARE:
            _ = await flash_esc_firmware(state, serial_manager, show_toasts=True)
        case _:
            if not await _handle_payload_message(state, payload, message):
                log_warn(f"Received unhandled message type: {message.type}")
