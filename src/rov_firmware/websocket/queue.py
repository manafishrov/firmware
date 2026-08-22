"""WebSocket message queue for the ROV firmware."""

import asyncio
from dataclasses import dataclass

from .message import WebsocketMessage


@dataclass(slots=True)
class ConfirmedMessage:
    """A queued frame whose producer must know whether it reached the socket."""

    message: WebsocketMessage
    sent: asyncio.Future[None]


QueuedMessage = WebsocketMessage | ConfirmedMessage
message_queue: asyncio.Queue[QueuedMessage] = asyncio.Queue()


def get_message_queue() -> asyncio.Queue[QueuedMessage]:
    """Get the message queue.

    Returns:
        The message queue.
    """
    return message_queue


async def send_message_and_wait(
    message: WebsocketMessage, *, timeout: float = 3.0
) -> None:
    """Queue a frame and wait until the active server writes it to the socket."""
    sent = asyncio.get_running_loop().create_future()
    await message_queue.put(ConfirmedMessage(message=message, sent=sent))
    await asyncio.wait_for(sent, timeout=timeout)
