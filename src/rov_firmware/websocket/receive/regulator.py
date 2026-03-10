"""WebSocket regulator handlers for the ROV firmware."""

import time

from ...constants import AUTO_TUNING_TOAST_ID, MAX_AUTO_TUNING_ROLL_PITCH_DEGREES
from ...log import log_error, log_info
from ...models.toast import ToastVariant
from ...rov_state import RovState
from ...toast import (
    ToastContent,
    cancel_regulator_auto_tuning_action,
    toast_content,
    toast_error,
)


async def handle_start_regulator_auto_tuning(
    state: RovState,
) -> None:
    """Handle starting regulator auto tuning.

    Args:
        state: The ROV state.
    """
    log_info("Starting regulator auto tuning")

    if not state.system_health.imu_healthy:
        log_error("IMU not healthy, cannot start auto tuning")
        toast_error(
            identifier=AUTO_TUNING_TOAST_ID,
            content=ToastContent(
                message_key="toasts_auto_tuning_failed",
                description_key="toasts_auto_tuning_failed_imu_unhealthy",
            ),
            action=None,
        )
        return

    if not state.system_health.pressure_sensor_healthy:
        log_error("Pressure sensor not healthy, cannot start auto tuning")
        toast_error(
            identifier=AUTO_TUNING_TOAST_ID,
            content=ToastContent(
                message_key="toasts_auto_tuning_failed",
                description_key="toasts_auto_tuning_failed_pressure_unhealthy",
            ),
            action=None,
        )
        return

    if abs(state.regulator.roll) > MAX_AUTO_TUNING_ROLL_PITCH_DEGREES:
        log_error(
            f"ROV roll too high: {state.regulator.roll}°, cannot start auto tuning"
        )
        toast_error(
            identifier=AUTO_TUNING_TOAST_ID,
            content=ToastContent(
                message_key="toasts_auto_tuning_failed",
                description_key="toasts_auto_tuning_failed_roll_not_level",
                description_args={"roll": round(state.regulator.roll, 1)},
            ),
            action=None,
        )
        return

    if abs(state.regulator.pitch) > MAX_AUTO_TUNING_ROLL_PITCH_DEGREES:
        log_error(
            f"ROV pitch too high: {state.regulator.pitch}°, cannot start auto tuning"
        )
        toast_error(
            identifier=AUTO_TUNING_TOAST_ID,
            content=ToastContent(
                message_key="toasts_auto_tuning_failed",
                description_key="toasts_auto_tuning_failed_pitch_not_level",
                description_args={"pitch": round(state.regulator.pitch, 1)},
            ),
            action=None,
        )
        return

    state.regulator.desired_depth = state.pressure.depth
    state.regulator.auto_tuning_active = True
    state.regulator.auto_tuning_start_time = time.time()
    toast_content(
        identifier=AUTO_TUNING_TOAST_ID,
        variant=ToastVariant.LOADING,
        content=ToastContent(
            message_key="toasts_auto_tuning_starting",
            description_key="toasts_auto_tuning_finding_zero",
        ),
        action=cancel_regulator_auto_tuning_action(),
    )


async def handle_cancel_regulator_auto_tuning(
    state: RovState,
) -> None:
    """Handle cancelling regulator auto tuning.

    Args:
        state: The ROV state.
    """
    log_info("Cancelling regulator auto tuning")
    state.regulator.auto_tuning_active = False
    toast_content(
        identifier=AUTO_TUNING_TOAST_ID,
        variant=ToastVariant.INFO,
        content=ToastContent(
            message_key="toasts_auto_tuning_cancelled",
        ),
        action=None,
    )
