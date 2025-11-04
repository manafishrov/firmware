"""WebSocket status send handlers for the ROV firmware."""

from __future__ import annotations

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
    temps: list[float] = []
    if state.imu.temperature > 0:
        temps.append(state.imu.temperature)
    temps.extend(t for t in state.esc.temperature if t > 0)
    electronics_temperature = sum(temps) / len(temps) if temps else 0

    voltages_v = [cv / 100 for cv in state.esc.voltage_cv if cv > 0]
    average_voltage_v = sum(voltages_v) / len(voltages_v) if voltages_v else 0
    min_v = state.rov_config.power.battery_min_voltage
    max_v = state.rov_config.power.battery_max_voltage
    current_percentage = (
        max(0, min(100, ((average_voltage_v - min_v) / (max_v - min_v)) * 100))
        if average_voltage_v
        else 0
    )
    state.system_status.battery_percentage = (
        BATTERY_EMA_ALPHA * current_percentage
        + (1 - BATTERY_EMA_ALPHA) * state.system_status.battery_percentage
    )

    payload = RovStatus(
        pitch_stabilization=state.system_status.pitch_stabilization,
        roll_stabilization=state.system_status.roll_stabilization,
        depth_hold=state.system_status.depth_hold,
        battery_percentage=int(state.system_status.battery_percentage),
        depth=state.pressure.depth,
        water_temperature=state.pressure.temperature,
        electronics_temperature=electronics_temperature,
    )
    message = StatusUpdate(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
