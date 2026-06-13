"""WebSocket server for the ROV firmware."""

import asyncio
import json
import logging
from typing import cast

from pydantic import TypeAdapter
import websockets
from websockets import Server, ServerConnection
from websockets.exceptions import ConnectionClosed

from ..constants import CRASH_LOG_SEND_TIMEOUT_S
from ..log import flush_pending_logs, log_error, log_info, log_warn
from ..models.log import LogEntry, LogLevel, LogOrigin
from ..rov_state import RovState
from .handler import handle_message
from .message import LogMessage, WebsocketMessage
from .queue import get_message_queue
from .send.config import handle_send_config
from .send.status import handle_status_update
from .send.telemetry import handle_telemetry
from .state import websocket_state


_logger = logging.getLogger(__name__)

websocket_message_adapter = TypeAdapter(WebsocketMessage)


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
        self._send_lock: asyncio.Lock = asyncio.Lock()

    async def handler(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connection.

        Args:
            websocket: The WebSocket.
        """
        self.client = websocket
        websocket_state.is_client_connected = True
        log_info(
            f"Client connected: {cast(tuple[str, int] | None, websocket.remote_address)}."
        )

        send_task = asyncio.create_task(self._send_from_queue(websocket))
        await flush_pending_logs()
        status_task = asyncio.create_task(
            self._send_status_periodically(websocket, self.state)
        )
        telemetry_task = asyncio.create_task(
            self._send_telemetry_periodically(websocket, self.state)
        )

        async def send_config_on_connect() -> None:
            await asyncio.sleep(5)
            try:
                await handle_send_config(websocket, self.state)
                log_info(
                    f"Sent config to {cast(tuple[str, int] | None, websocket.remote_address)}"
                )
            except ConnectionClosed:
                log_warn(
                    f"Client disconnected before config could be sent to {cast(tuple[str, int] | None, websocket.remote_address)}"
                )
            except Exception as e:
                log_error(f"Error sending initial data: {e}")

        config_task = asyncio.create_task(send_config_on_connect())

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    deserialized_msg = websocket_message_adapter.validate_python(data)
                    await handle_message(self.state, websocket, deserialized_msg)
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
            _ = config_task.cancel()
            self.client = None
            websocket_state.is_client_connected = False
            log_info("Client disconnected.")

    async def initialize(self) -> None:
        """Initialize the WebSocket server."""
        self.server = await websockets.serve(
            self.handler,
            self.state.rov_config.ip_address,
            self.state.rov_config.websocket_port,
        )
        websocket_state.main_event_loop = asyncio.get_running_loop()
        log_info(
            f"Websocket server started on {self.state.rov_config.ip_address}:{self.state.rov_config.websocket_port}"
        )

    async def send_log_now(self, level: LogLevel, message: str) -> None:
        """Send a single log frame directly, bypassing the message queue.

        Args:
            level: The log level for the frame.
            message: The log message body.
        """
        client = self.client
        if client is None:
            return

        payload = LogEntry(origin=LogOrigin.FIRMWARE, level=level, message=message)
        frame = LogMessage(payload=payload).model_dump_json(by_alias=True)
        try:
            async with self._send_lock:
                await asyncio.wait_for(client.send(frame), CRASH_LOG_SEND_TIMEOUT_S)
        except Exception:
            _logger.exception("Failed to send final websocket crash log")

    async def _send_from_queue(self, websocket: ServerConnection) -> None:
        try:
            while True:
                message = await get_message_queue().get()
                try:
                    json_msg = message.model_dump_json(by_alias=True)
                    async with self._send_lock:
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
