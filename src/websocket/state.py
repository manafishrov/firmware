"""Shared state for WebSocket-related async utilities."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class AsyncWebSocketState(BaseModel):
    """Shared state for WebSocket async utilities."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    is_client_connected: bool = False
    main_event_loop: asyncio.AbstractEventLoop | None = None


websocket_state = AsyncWebSocketState()


def set_client_connected(is_connected: bool) -> None:
    """Set the client connected status.

    Args:
        is_connected: Whether the client is connected.
    """
    websocket_state.is_client_connected = is_connected


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Set the main event loop.

    Args:
        loop: The asyncio event loop.
    """
    websocket_state.main_event_loop = loop
