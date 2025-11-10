"""WebSocket state handlers for the ROV firmware."""

from __future__ import annotations

from ...log import log_info
from ...rov_state import RovState


async def handle_toggle_pitch_stabilization(
    state: RovState,
) -> None:
    """Handle toggling pitch stabilization.

    Args:
        state: The ROV state.
    """
    state.system_status.pitch_stabilization = (
        not state.system_status.pitch_stabilization
    )
    log_info(
        f"Toggled pitch stabilization to {state.system_status.pitch_stabilization}"
    )


async def handle_toggle_roll_stabilization(
    state: RovState,
) -> None:
    """Handle toggling roll stabilization.

    Args:
        state: The ROV state.
    """
    state.system_status.roll_stabilization = not state.system_status.roll_stabilization
    log_info(f"Toggled roll stabilization to {state.system_status.roll_stabilization}")


async def handle_toggle_depth_hold(
    state: RovState,
) -> None:
    """Handle toggling depth hold.

    Args:
        state: The ROV state.
    """
    state.system_status.depth_hold = not state.system_status.depth_hold
    log_info(f"Toggled depth hold to {state.system_status.depth_hold}")
