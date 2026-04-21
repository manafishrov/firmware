"""WebSocket status send handlers for the ROV firmware."""

from websockets import ServerConnection

from ...constants import BATTERY_EMA_ALPHA
from ...models.rov_status import RovStatus
from ...rov_state import RovState
from ..message import StatusUpdate


async def handle_status_update(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    """Handle sending status update.

    Args:
        websocket: The WebSocket connection.
        state: The ROV state.
    """
    power = state.rov_config.power

    voltage_sum = 0.0
    voltage_count = 0
    current_sum = 0.0
    for i, voltage in enumerate(state.mcu_telemetry.voltage):
        if voltage > 0:
            voltage_sum += voltage
            voltage_count += 1
            current_sum += state.mcu_telemetry.current[i]

    average_voltage_v = voltage_sum / voltage_count if voltage_count > 0 else 0

    # Compensate for voltage sag: V_unloaded = V_measured + I_total * R_internal
    if average_voltage_v > 0 and power.internal_resistance > 0:
        average_voltage_v += current_sum * power.internal_resistance

    min_v = power.min_battery_voltage
    max_v = power.max_battery_voltage
    current_percentage = (
        max(0.0, min(100.0, ((average_voltage_v - min_v) / (max_v - min_v)) * 100))
        if average_voltage_v
        else 0.0
    )

    state.system_status.battery_percentage = (
        BATTERY_EMA_ALPHA * current_percentage
        + (1 - BATTERY_EMA_ALPHA) * state.system_status.battery_percentage
    )

    payload = RovStatus(
        auto_stabilization=state.system_status.auto_stabilization,
        depth_hold=state.system_status.depth_hold,
        battery_percentage=int(state.system_status.battery_percentage),
        health=state.system_health,
    )
    message = StatusUpdate(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
