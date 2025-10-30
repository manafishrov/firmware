"""WebSocket regulator handlers for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rov_state import RovState

import time

from ...constants import AUTO_TUNING_TOAST_ID
from ...log import log_error, log_info
from ...toast import toast_error, toast_info, toast_loading
from ...websocket.message import CancelRegulatorAutoTuning


async def handle_start_regulator_auto_tuning(
    state: RovState,
) -> None:
    log_info("Starting regulator auto tuning")

    if not state.system_health.imu_ok:
        log_error("IMU not healthy, cannot start auto tuning")
        toast_error(
            toast_id=AUTO_TUNING_TOAST_ID,
            message="Auto tuning failed",
            description="IMU sensor not healthy",
            cancel=None,
        )
        return

    if not state.system_health.pressure_sensor_ok:
        log_error("Pressure sensor not healthy, cannot start auto tuning")
        toast_error(
            toast_id=AUTO_TUNING_TOAST_ID,
            message="Auto tuning failed",
            description="Pressure sensor not healthy",
            cancel=None,
        )
        return

    if abs(state.regulator.roll) > 10:
        log_error(
            f"ROV roll too high: {state.regulator.roll}°, cannot start auto tuning"
        )
        toast_error(
            toast_id=AUTO_TUNING_TOAST_ID,
            message="Auto tuning failed",
            description=f"ROV roll is {state.regulator.roll:.1f}°, must be level",
            cancel=None,
        )
        return

    if abs(state.regulator.pitch) > 10:
        log_error(
            f"ROV pitch too high: {state.regulator.pitch}°, cannot start auto tuning"
        )
        toast_error(
            toast_id=AUTO_TUNING_TOAST_ID,
            message="Auto tuning failed",
            description=f"ROV pitch is {state.regulator.pitch:.1f}°, must be level",
            cancel=None,
        )
        return

    state.regulator.desired_depth = state.pressure.depth
    state.regulator.auto_tuning_active = True
    state.regulator.auto_tuning_start_time = time.time()
    toast_loading(
        toast_id=AUTO_TUNING_TOAST_ID,
        message="Starting regulator auto tuning",
        description="Preparing...",
        cancel=CancelRegulatorAutoTuning(),
    )


async def handle_cancel_regulator_auto_tuning(
    state: RovState,
) -> None:
    log_info("Cancelling regulator auto tuning")
    state.regulator.auto_tuning_active = False
    toast_info(
        toast_id="regulator-auto-tuning",
        message="Auto tuning cancelled",
        description=None,
        cancel=None,
    )
