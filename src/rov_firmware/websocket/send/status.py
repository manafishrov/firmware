"""WebSocket status send handlers for the ROV firmware."""

from ...models.rov_status import RovStatus
from ...rov_state import RovState
from ..message import StatusUpdate


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
    current_draw = sum(state.mcu_telemetry.current)

    payload = RovStatus(
        auto_stabilization=state.system_status.auto_stabilization,
        depth_hold=state.system_status.depth_hold,
        battery_percentage=int(state.system_status.battery_percentage),
        current_draw=current_draw,
        health=state.system_health,
    )
    return StatusUpdate(payload=payload)
