"""Example custom action handler for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rov_state import RovState

from ..log import log_info
from ..toast import toast_info


async def execute(state: RovState) -> None:  # noqa: ARG001
    """This is an example of a custom action handler. You can create your own custom action by creating a new file in the `custom_actions`. They all have access to the `RovState` which is where all interactions with the firmware happen and where all the raw and processed data is stored."""
    log_info("Executing example custom action")
    toast_info(
        toast_id=None,
        message="Example action triggered",
        description="This is a sample custom action",
        cancel=None,
    )
