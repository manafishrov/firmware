from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol

    from rov_state import RovState

from ...log import log_info
from ...models.config import RovConfig
from ...toast import toast_success
from ..message import Config


async def handle_get_config(
    state: RovState,
    websocket: WebSocketServerProtocol,
) -> None:
    msg = Config(payload=state.rov_config).json(by_alias=True)
    await websocket.send(msg)
    log_info("Sent config to client.")


async def handle_set_config(
    state: RovState,
    payload: RovConfig,
) -> None:
    state.rov_config = payload
    state.rov_config.save()
    log_info("Received and applied new config.")
    toast_success(
        id=None,
        message="ROV config set successfully",
        description=None,
        cancel=None,
    )
