"""WebSocket status send handlers for the ROV firmware."""

import time

from ...constants import MCU_TELEMETRY_STALE_TIMEOUT_S
from ...models.config import ThrusterProtocol
from ...models.rov_status import RovStatus
from ...rov_state import RovState
from ...sensors.pi_power import is_pi_undervoltage_detected
from ..message import StatusUpdate


def _current_draw(state: RovState) -> float | None:
    """Sum two fresh MCU-calibrated board reports, never raw ESC readings."""
    if (
        not state.system_health.mcu_healthy
        or state.rov_config.thruster_protocol != ThrusterProtocol.DSHOT
        or state.mcu_flashing
        or state.esc_firmware_update.active
        or state.esc_firmware_recovery_required
    ):
        return None
    telemetry = state.mcu_telemetry
    now = time.monotonic()
    total_ma = 0
    for value, updated in zip(
        telemetry.board_current_ma, telemetry.board_current_updated_at, strict=True
    ):
        if (
            value is None
            or updated <= 0
            or now - updated > MCU_TELEMETRY_STALE_TIMEOUT_S
        ):
            return None
        total_ma += value
    return total_ma / 1000


def build_status_update(state: RovState) -> StatusUpdate:
    """Build a status update message from the current ROV state.

    Args:
        state: The ROV state.

    Returns:
        The status update message ready to be sent.
    """
    voltages_v = [v for v in state.mcu_telemetry.voltage if v > 0]
    average_voltage_v = sum(voltages_v) / len(voltages_v) if voltages_v else 0
    min_v = state.rov_config.power.min_battery_voltage
    max_v = state.rov_config.power.max_battery_voltage
    state.system_status.battery_percentage = (
        max(0, min(100, ((average_voltage_v - min_v) / (max_v - min_v)) * 100))
        if average_voltage_v
        else 0
    )
    current_draw = _current_draw(state)

    payload = RovStatus(
        auto_stabilization=state.system_status.auto_stabilization,
        depth_hold=state.system_status.depth_hold,
        battery_percentage=int(state.system_status.battery_percentage),
        current_draw=current_draw,
        pi_undervoltage=is_pi_undervoltage_detected(),
        thruster_control_ready=state.system_status.thruster_control_ready,
        thruster_protocol_state=state.system_status.thruster_protocol_state,
        thruster_protocol_error=state.system_status.thruster_protocol_error,
        health=state.system_health,
        device_info=state.device_info,
        esc_firmware_update=state.esc_firmware_update,
    )
    return StatusUpdate(payload=payload)
