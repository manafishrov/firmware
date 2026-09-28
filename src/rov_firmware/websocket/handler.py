"""WebSocket message handler for the ROV firmware."""

from typing import cast

from ..esc_firmware import flash_esc_firmware
from ..log import log_warn
from ..models.config import (
    McuBoard,
    ThrusterTest,
)
from ..rov_state import RovState
from ..serial import SerialManager
from .message import ImportConfigPayload, SetConfigPayload, WebsocketMessage
from .receive.actions import (
    handle_cancel_thruster_test,
    handle_start_thruster_test,
)
from .receive.config import (
    handle_confirm_config,
    handle_get_config,
    handle_import_config,
    handle_set_config,
)
from .receive.mcu import handle_flash_mcu_firmware
from .receive.regulator import (
    handle_cancel_regulator_auto_tuning,
    handle_start_regulator_auto_tuning,
)
from .types import MessageType


async def _handle_payload_message(
    state: RovState,
    payload: object,
    message: WebsocketMessage,
) -> bool:
    match message.type:
        case MessageType.SET_CONFIG:
            mutation = cast(SetConfigPayload, payload)
            await handle_set_config(state, mutation.config, mutation.mutation_id)
        case MessageType.IMPORT_CONFIG:
            mutation = cast(ImportConfigPayload, payload)
            await handle_import_config(state, mutation.config, mutation.mutation_id)
        case MessageType.FLASH_MCU_FIRMWARE:
            await handle_flash_mcu_firmware(state, cast(McuBoard, payload))
        case MessageType.START_THRUSTER_TEST:
            await handle_start_thruster_test(state, cast(ThrusterTest, payload))
        case MessageType.CANCEL_THRUSTER_TEST:
            await handle_cancel_thruster_test(state, cast(ThrusterTest, payload))
        case _:
            return False

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
        case MessageType.CONFIRM_CONFIG:
            handle_confirm_config(state, cast(str, payload))
        case MessageType.START_REGULATOR_AUTO_TUNING:
            await handle_start_regulator_auto_tuning(state)
        case MessageType.CANCEL_REGULATOR_AUTO_TUNING:
            await handle_cancel_regulator_auto_tuning(state)
        case MessageType.FLASH_ESC_FIRMWARE:
            _ = await flash_esc_firmware(state, serial_manager, show_toasts=True)
        case _:
            if not await _handle_payload_message(state, payload, message):
                log_warn(f"Received unhandled message type: {message.type}")
