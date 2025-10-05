from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import RovState

from ...log import log_info


async def handle_start_regulator_auto_tuning(
    state: RovState,
) -> None:
    log_info("Starting regulator auto tuning")


async def handle_cancel_regulator_auto_tuning(
    state: RovState,
) -> None:
    log_info("Cancelling regulator auto tuning")
