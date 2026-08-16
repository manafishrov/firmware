"""WebSocket state handlers for the ROV firmware."""

from ...log import log_info
from ...rov_state import RovState


async def handle_toggle_auto_stabilization(
    state: RovState,
) -> None:
    """Handle toggling auto stabilization.

    Args:
        state: The ROV state.
    """
    state.system_status.auto_stabilization = not state.system_status.auto_stabilization
    if not state.system_status.auto_stabilization:
        state.regulator.desired_pitch = 0.0
        state.regulator.desired_roll = 0.0
    log_info(f"Toggled auto stabilization to {state.system_status.auto_stabilization}")


async def handle_set_auto_stabilization(state: RovState, enabled: bool) -> None:
    """Set auto stabilization to the requested state."""
    state.system_status.auto_stabilization = enabled
    if not enabled:
        state.regulator.desired_pitch = 0.0
        state.regulator.desired_roll = 0.0
    log_info(f"Set auto stabilization to {enabled}")


async def handle_toggle_depth_hold(
    state: RovState,
) -> None:
    """Handle toggling depth hold.

    Args:
        state: The ROV state.
    """
    state.system_status.depth_hold = not state.system_status.depth_hold
    if state.system_status.depth_hold:
        pending = state.regulator.pending_desired_depth
        if pending is not None:
            state.regulator.desired_depth = pending
        else:
            state.regulator.desired_depth = state.pressure.depth
    else:
        state.regulator.pending_desired_depth = None
    log_info(f"Toggled depth hold to {state.system_status.depth_hold}")


async def handle_set_depth_hold(state: RovState, enabled: bool) -> None:
    """Set depth hold to the requested state."""
    if enabled and not state.system_status.depth_hold:
        pending = state.regulator.pending_desired_depth
        state.regulator.desired_depth = (
            pending if pending is not None else state.pressure.depth
        )
    if not enabled:
        state.regulator.pending_desired_depth = None
    state.system_status.depth_hold = enabled
    log_info(f"Set depth hold to {enabled}")
