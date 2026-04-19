"""WebSocket action handlers for the ROV firmware."""

import importlib
import time

from ...constants import THRUSTER_TEST_TOAST_ID
from ...log import log_error, log_info, log_warn
from ...models.actions import CustomAction, DirectionVector
from ...models.config import ThrusterTest
from ...models.toast import ToastVariant
from ...rov_state import RovState
from ...toast import ToastContent, cancel_thruster_test_action, toast_content


async def handle_direction_vector(
    state: RovState,
    payload: DirectionVector,
) -> None:
    """Handle direction vector message.

    Args:
        state: The ROV state.
        payload: The direction vector.
    """
    state.thrusters.direction_vector = payload.root
    state.thrusters.last_direction_time = time.time()


async def handle_start_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    """Handle start thruster test message.

    Args:
        state: The ROV state.
        payload: The thruster test index.
    """
    log_info(f"Starting thruster test: {payload}")
    state.thrusters.test_thruster = payload
    state.thrusters.test_start_time = time.time()
    state.thrusters.last_remaining = 10
    toast_content(
        identifier=THRUSTER_TEST_TOAST_ID,
        variant=ToastVariant.LOADING,
        content=ToastContent(
            message_key="toasts_thruster_test_title",
            message_args={"thruster": payload},
            description_key="toasts_seconds_remaining",
            description_args={"seconds": 10},
        ),
        action=cancel_thruster_test_action(payload),
    )


async def handle_cancel_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    """Handle cancel thruster test message.

    Args:
        state: The ROV state.
        payload: The thruster test configuration.
    """
    log_info(f"Cancelling thruster test: {payload}")
    state.thrusters.test_thruster = None
    toast_content(
        identifier=THRUSTER_TEST_TOAST_ID,
        variant=ToastVariant.INFO,
        content=ToastContent(
            message_key="toasts_thruster_test_cancelled",
        ),
        action=None,
    )


async def handle_custom_action(
    state: RovState,
    payload: CustomAction,
) -> None:
    """Handle custom action message.

    Args:
        state: The ROV state.
        payload: The custom action to execute.
    """
    log_info(f"Received custom action: {payload}")
    try:
        module = importlib.import_module(f"rov_firmware.custom_actions.{payload}")
        if hasattr(module, "execute"):
            await module.execute(state)
        else:
            log_warn(f"Custom action {payload} has no 'execute' function")
    except ImportError:
        log_warn(f"Custom action {payload} not found")
    except Exception as e:
        log_error(f"Error executing custom action {payload}: {e}")
