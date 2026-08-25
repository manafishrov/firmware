"""Shared safety checks for operations that interrupt thruster output."""

from .models.system import EscFirmwareUpdateStage
from .rov_state import RovState


def motor_firmware_operation_blocker(state: RovState) -> str | None:
    """Return why a motor-control feature cannot be enabled right now."""
    if state.esc_firmware_recovery_required:
        return "ESC firmware recovery must finish first"
    if state.mcu_flashing:
        return "a firmware update is active"
    return None


def disruptive_motor_operation_blocker(
    state: RovState, *, allow_esc_recovery: bool = False
) -> str | None:
    """Return why a flash or signal change cannot safely start."""
    blockers = (
        (
            state.esc_firmware_recovery_required and not allow_esc_recovery,
            "ESC firmware recovery must finish first",
        ),
        (state.mcu_flashing, "a firmware update is active"),
        (
            state.esc_firmware_update.stage
            == EscFirmwareUpdateStage.AWAITING_TELEMETRY,
            "ESC firmware version confirmation is still running",
        ),
        (state.regulator.auto_tuning_active, "regulator auto-tuning is active"),
        (state.thrusters.test_thruster is not None, "a thruster test is active"),
        (state.system_status.auto_stabilization, "auto-stabilization is active"),
        (state.system_status.depth_hold, "depth hold is active"),
    )
    for blocked, reason in blockers:
        if blocked:
            return reason
    direction = state.thrusters.direction_vector
    if direction is not None and any(float(value) != 0.0 for value in direction):
        return "pilot input is not neutral"
    return None
