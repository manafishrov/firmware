"""Shared state for WebSocket-related async utilities."""


import asyncio
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class AsyncWebSocketState(BaseModel):
    """Shared state for WebSocket async utilities."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    is_client_connected: bool = False
    main_event_loop: asyncio.AbstractEventLoop | None = None


websocket_state = AsyncWebSocketState()
