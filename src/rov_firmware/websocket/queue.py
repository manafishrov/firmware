"""WebSocket message queue for the ROV firmware."""


import asyncio

from .message import WebsocketMessage


message_queue: asyncio.Queue[WebsocketMessage] = asyncio.Queue()


def get_message_queue() -> asyncio.Queue[WebsocketMessage]:
    """Get the message queue.

    Returns:
        The message queue.
    """
    return message_queue
