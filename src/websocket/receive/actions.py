from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

import time
from ...log import log_info
from ...models.actions import DirectionVector, CustomAction
from ...models.config import ThrusterTest
from ...toast import toast_loading, toast_success, toast_info
from ...websocket.message import CancelThrusterTest


async def handle_direction_vector(
    state: RovState,
    payload: DirectionVector,
) -> None:
    log_info(f"Received direction vector: {payload}")
    state.thrusters.direction_vector = payload.root
    state.thrusters.last_direction_time = time.time()


async def handle_start_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    log_info(f"Starting thruster test: {payload}")
    state.thrusters.test_thruster = payload
    state.thrusters.test_start_time = time.time()
    state.thrusters.last_remaining = 10
    toast_loading(
        id="thruster-test",
        message=f"Testing thruster {payload}",
        description="10 seconds remaining",
        cancel=CancelThrusterTest(payload=payload),
    )


async def handle_cancel_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    log_info(f"Cancelling thruster test: {payload}")
    state.thrusters.test_thruster = None
    toast_info(
        id="thruster-test",
        message="Thruster test cancelled",
        description=None,
        cancel=None,
    )


async def handle_custom_action(
    state: RovState,
    payload: CustomAction,
) -> None:
    log_info(f"Received custom action: {payload}")
