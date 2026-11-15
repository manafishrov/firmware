"""WebSocket regulator handlers for the ROV firmware."""

import math

from ...log import log_error, log_info
from ...models.toast import ToastContent
from ...rov_state import RovState
from ...toast import toast_warn


async def handle_set_desired_depth(
    state: RovState,
    depth: float,
) -> None:
    """Update the regulator target depth from a websocket command."""
    if not math.isfinite(depth):
        log_error(f"Invalid desired depth received: {depth}")
        return

    desired_depth = max(0.0, depth)
    if state.pico is not None:
        try:
            await state.set_desired_depth(desired_depth)
        except Exception as error:
            log_error(f"Desired depth was not confirmed by Pico: {error}")
            toast_warn(
                identifier=None,
                content=ToastContent(
                    message_key="toasts_invoke_failed",
                    message_args={"command": "setDesiredDepth"},
                    description_key="toasts_disruptive_config_blocked_description",
                    description_args={"reason": str(error)},
                ),
                action=None,
            )
            raise
    state.regulator.pending_desired_depth = desired_depth
    if state.system_status.depth_hold:
        state.regulator.desired_depth = desired_depth
    log_info(f"Set desired depth to {desired_depth}")
