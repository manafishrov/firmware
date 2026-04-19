"""WebSocket telemetry send handlers for the ROV firmware."""

from websockets import ServerConnection

from ...constants import THRUSTER_POLES
from ...models.rov_telemetry import RovTelemetry
from ...rov_state import RovState
from ..message import Telemetry


async def handle_telemetry(
    websocket: ServerConnection,
    state: RovState,
) -> None:
    """Handle sending telemetry data.

    Args:
        websocket: The WebSocket connection.
        state: The ROV state.
    """
    temps: list[float] = []
    if state.imu.temperature > 0:
        temps.append(state.imu.temperature)
    temps.extend(t for t in state.mcu_telemetry.temperature if t > 0)
    electronics_temperature = sum(temps) / len(temps) if temps else 0

    if state.system_status.depth_hold:
        desired_depth = state.regulator.desired_depth
    elif state.regulator.pending_desired_depth is not None:
        desired_depth = state.regulator.pending_desired_depth
    else:
        desired_depth = state.pressure.depth
    payload = RovTelemetry(
        pitch=state.regulator.pitch,
        roll=state.regulator.roll,
        yaw=state.regulator.yaw,
        depth=state.pressure.depth,
        desired_pitch=state.regulator.desired_pitch,
        desired_roll=state.regulator.desired_roll,
        desired_yaw=state.regulator.desired_yaw,
        desired_depth=desired_depth,
        water_temperature=state.pressure.temperature,
        electronics_temperature=electronics_temperature,
        thruster_rpms=[
            int(erpm / (THRUSTER_POLES // 2)) for erpm in state.mcu_telemetry.erpm
        ],
        thruster_signal_qualities=list(state.mcu_telemetry.signal_quality),
        work_indicator_percentage=state.thrusters.work_indicator_percentage,
    )
    message = Telemetry(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
