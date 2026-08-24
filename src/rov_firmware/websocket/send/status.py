"""WebSocket status send handlers for the ROV firmware."""

from ...constants import MOTORS_PER_BUS
from ...models.config import CurrentSensingMode
from ...models.rov_status import RovStatus
from ...rov_state import RovState
from ...sensors.pi_power import is_pi_undervoltage_detected
from ..message import StatusUpdate


def _current_draw(state: RovState) -> int:
    """Return total live ESC current in amperes without double-counting buses."""
    currents = state.mcu_telemetry.current
    valid = state.mcu_telemetry.current_valid

    if state.rov_config.current_sensing_mode == CurrentSensingMode.PER_MOTOR:
        return sum(
            value for value, is_valid in zip(currents, valid, strict=False) if is_valid
        )

    total = 0.0
    for start in range(0, len(currents), MOTORS_PER_BUS):
        bus_currents = [
            value
            for value, is_valid in zip(
                currents[start : start + MOTORS_PER_BUS],
                valid[start : start + MOTORS_PER_BUS],
                strict=False,
            )
            if is_valid
        ]
        if bus_currents:
            # Every controller on a 4-in-1 ESC reports the same board-level
            # shunt. Average only fresh copies, then count that bus once.
            total += sum(bus_currents) / len(bus_currents)
    # EDT itself has 1 A resolution, so keep the established integer WebSocket
    # contract and round only after all shared-bus copies have been averaged.
    return int(total + 0.5)


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
        health=state.system_health,
        device_info=state.device_info,
        esc_firmware_update=state.esc_firmware_update,
    )
    return StatusUpdate(payload=payload)
