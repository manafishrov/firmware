"""WebSocket config send handlers for the ROV firmware."""

from ...rov_state import RovState
from ..message import Config


def build_config(state: RovState) -> Config:
    """Build a config message from the current ROV state.

    Args:
        state: The ROV state.

    Returns:
        The config message ready to be sent.
    """
    return Config(payload=state.rov_config)
