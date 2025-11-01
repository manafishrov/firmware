"""WebSocket server for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from websockets import Server, ServerConnection
    from websockets.exceptions import ConnectionClosed

    from rov_state import RovState

import asyncio
import json

import websockets

from ..constants import FIRMWARE_VERSION, IP_ADDRESS, PORT
from ..log import log_error, log_info, log_warn, set_log_is_client_connected_status
from ..websocket.handler import handle_message
from ..websocket.send.config import handle_send_config, handle_send_firmware_version
from .message import WebsocketMessage
from .send.status import handle_status_update
from .send.telemetry import handle_telemetry


message_queue: asyncio.Queue[WebsocketMessage] = asyncio.Queue()


def get_message_queue() -> asyncio.Queue[WebsocketMessage]:
    """Get the message queue.

    Returns:
        The message queue.
    """
    return message_queue


class WebsocketServer:
    """WebSocket server class."""

    def __init__(self, state: RovState) -> None:
        """Initialize the WebSocket server.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.server: Server | None = None
        self.client: ServerConnection | None = None

    async def handler(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connection.

        Args:
            websocket: The WebSocket.
        """
        self.client = websocket
        set_log_is_client_connected_status(True)
        log_info(
            f"Client connected: {cast(tuple[str, int] | None, websocket.remote_address)}."
        )

        send_task = asyncio.create_task(self._send_from_queue(websocket))
        status_task = asyncio.create_task(
            self._send_status_periodically(websocket, self.state)
        )
        telemetry_task = asyncio.create_task(
            self._send_telemetry_periodically(websocket, self.state)
        )

        async def send_firmware_version_on_connect() -> None:
            await asyncio.sleep(5)
            try:
                await handle_send_firmware_version(websocket)
                log_info(
                    f"Sent firmware version '{FIRMWARE_VERSION}' to {cast(tuple[str, int] | None, websocket.remote_address)}"
                )
                await handle_send_config(websocket, self.state)
                log_info(
                    f"Sent config to {cast(tuple[str, int] | None, websocket.remote_address)}"
                )
            except ConnectionClosed:
                log_warn(
                    f"Client disconnected before firmware version and config could be sent to {cast(tuple[str, int] | None, websocket.remote_address)}"
                )
            except Exception as e:
                log_error(f"Error sending initial data: {e}")

        firmware_task = asyncio.create_task(send_firmware_version_on_connect())

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)  # pyright: ignore[reportAny]
                    deserialized_msg = WebsocketMessage(**data)  # pyright: ignore[reportCallIssue]
                    await handle_message(self.state, websocket, deserialized_msg)  # pyright: ignore[reportUnknownArgumentType]
                except json.JSONDecodeError:
                    log_warn(
                        f"Failed to deserialize message from {cast(tuple[str, int] | None, websocket.remote_address)}"
                    )
                except Exception as e:
                    log_warn(f"Error processing message: {e}")
        except ConnectionClosed:
            log_info(
                f"Client connection closed: {cast(tuple[str, int] | None, websocket.remote_address)}"
            )
        finally:
            _ = send_task.cancel()
            _ = status_task.cancel()
            _ = telemetry_task.cancel()
            _ = firmware_task.cancel()
            self.client = None
            set_log_is_client_connected_status(False)
            log_info("Client disconnected.")

    async def start(self) -> None:
        """Start the WebSocket server."""
        self.server = await websockets.serve(self.handler, IP_ADDRESS, PORT)
        log_info(f"Websocket server started on {IP_ADDRESS}:{PORT}")

    async def _send_from_queue(self, websocket: ServerConnection) -> None:
        try:
            while True:
                message = await message_queue.get()
                try:
                    json_msg = message.model_dump_json(by_alias=True)
                    await websocket.send(json_msg)
                except Exception as e:
                    log_error(f"Error sending queued message: {e}")
        except asyncio.CancelledError:
            pass

    async def _send_status_periodically(
        self, websocket: ServerConnection, state: RovState
    ) -> None:
        try:
            while True:
                await handle_status_update(websocket, state)
                await asyncio.sleep(1 / 2)
        except asyncio.CancelledError:
            pass

    async def _send_telemetry_periodically(
        self, websocket: ServerConnection, state: RovState
    ) -> None:
        try:
            while True:
                await handle_telemetry(websocket, state)
                await asyncio.sleep(1 / 60)
        except asyncio.CancelledError:
            pass

    async def wait_closed(self) -> None:
        """Wait for the server to close."""
        if self.server:
            await self.server.wait_closed()
