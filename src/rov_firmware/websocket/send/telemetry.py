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
    electronics_temperature_sum = 0.0
    electronics_temperature_count = 0

    if state.imu.temperature > 0:
        electronics_temperature_sum += state.imu.temperature
        electronics_temperature_count += 1

    for temperature in state.mcu_telemetry.temperature:
        if temperature > 0:
            electronics_temperature_sum += temperature
            electronics_temperature_count += 1

    electronics_temperature = (
        electronics_temperature_sum / electronics_temperature_count
        if electronics_temperature_count > 0
        else 0
    )

    if state.system_status.depth_hold:
        desired_depth = state.regulator.desired_depth
    elif state.regulator.pending_desired_depth is not None:
        desired_depth = state.regulator.pending_desired_depth
    else:
        desired_depth = state.pressure.depth
    thruster_rpms = [0] * len(state.mcu_telemetry.erpm)
    rpm_divisor = THRUSTER_POLES // 2
    for index, erpm in enumerate(state.mcu_telemetry.erpm):
        thruster_rpms[index] = int(erpm / rpm_divisor)

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
        thruster_rpms=thruster_rpms,
        thruster_signal_qualities=list(state.mcu_telemetry.signal_quality),
        work_indicator_percentage=state.thrusters.work_indicator_percentage,
    )
    message = Telemetry(payload=payload).model_dump_json(by_alias=True)
    await websocket.send(message)
