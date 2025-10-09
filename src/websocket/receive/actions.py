from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

import time
from ...log import log_info
from ...models.actions import DirectionVector, CustomAction
from ...models.config import ThrusterTest


async def handle_direction_vector(
    state: RovState,
    payload: DirectionVector,
) -> None:
    log_info(f"Received direction vector: {payload}")
    state.thruster_data.direction_vector = payload.root
    state.thruster_data.last_direction_time = time.time()


async def handle_start_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    log_info(f"Starting thruster test: {payload}")


async def handle_cancel_thruster_test(
    state: RovState,
    payload: ThrusterTest,
) -> None:
    log_info(f"Cancelling thruster test: {payload}")


async def handle_custom_action(
    state: RovState,
    payload: CustomAction,
) -> None:
    log_info(f"Received custom action: {payload}")
