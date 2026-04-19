"""WebSocket config handlers for the ROV firmware."""

import shutil
import subprocess

from websockets import ServerConnection

from ...log import log_info, log_warn
from ...models.config import PartialRovConfig, RovConfig
from ...rov_state import RovState
from ...toast import ToastContent, toast_info, toast_success
from ..message import Config


async def handle_get_config(
    state: RovState,
    websocket: ServerConnection,
) -> None:
    """Handle get config request.

    Args:
        state: The ROV state.
        websocket: The WebSocket connection.
    """
    msg = Config(payload=state.rov_config).model_dump_json(by_alias=True)
    await websocket.send(msg)
    log_info("Sent config to client.")


def _apply_ip_address(ip_address: str) -> None:
    path = shutil.which("manafish-network")
    if path is None:
        log_warn("manafish-network not found in PATH.")
        return
    try:
        subprocess.run(  # noqa: S603
            [path],
            check=True,
            capture_output=True,
        )
        log_info(f"Applied IP address change to {ip_address}.")
    except subprocess.CalledProcessError:
        log_warn(f"Failed to apply IP address change to {ip_address}.")


async def handle_set_config(
    state: RovState,
    payload: PartialRovConfig,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: Partial ROV configuration update.
    """
    old_ip = state.rov_config.ip_address
    current_data = state.rov_config.model_dump(by_alias=False)
    update_data = payload.model_dump(exclude_none=True, by_alias=False)
    current_data.update(update_data)
    state.rov_config = RovConfig.model_validate(current_data)
    state.rov_config.save()
    log_info("Received and applied config update.")

    if state.rov_config.ip_address != old_ip:
        toast_info(
            identifier=None,
            content=ToastContent(
                message_key="toasts_rov_ip_address_changing",
            ),
            action=None,
        )
        _apply_ip_address(state.rov_config.ip_address)

    toast_success(
        identifier=None,
        content=ToastContent(
            message_key="toasts_rov_config_set_successfully",
        ),
        action=None,
    )
