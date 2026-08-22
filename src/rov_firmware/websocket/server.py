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
from ..serial import SerialManager
from .handler import handle_message
from .message import LogMessage, WebsocketMessage
from .queue import ConfirmedMessage, get_message_queue
from .send.config import build_config
from .send.status import build_status_update
from .send.telemetry import build_telemetry
from .state import websocket_state


_logger = logging.getLogger(__name__)

websocket_message_adapter = TypeAdapter(WebsocketMessage)


class WebsocketServer:
    """WebSocket server class."""

    def __init__(self, state: RovState, serial_manager: SerialManager) -> None:
        """Initialize the WebSocket server.

        Args:
            state: The ROV state.
            serial_manager: The MCU serial connection used for ESC updates.
        """
        self.state: RovState = state
        self.serial_manager = serial_manager
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

        send_task = asyncio.create_task(self._send_from_queue())
        status_task: asyncio.Task[None] | None = None
        telemetry_task: asyncio.Task[None] | None = None
        try:
            await flush_pending_logs()
            await self.send_frame(build_config(self.state))
            log_info(
                f"Sent config to {cast(tuple[str, int] | None, websocket.remote_address)}"
            )
            status_task = asyncio.create_task(self._send_status_periodically())
            telemetry_task = asyncio.create_task(self._send_telemetry_periodically())

            async for message in websocket:
                try:
                    data = json.loads(message)
                    deserialized_msg = websocket_message_adapter.validate_python(data)
                    await handle_message(
                        self.state, self.serial_manager, deserialized_msg
                    )
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
        except Exception:
            _logger.exception("WebSocket connection handler failed")
        finally:
            tasks = [send_task]
            if status_task is not None:
                tasks.append(status_task)
            if telemetry_task is not None:
                tasks.append(telemetry_task)
            for task in tasks:
                _ = task.cancel()
            _ = await asyncio.gather(*tasks, return_exceptions=True)
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

    async def send_frame(
        self, message: WebsocketMessage, *, timeout: float | None = None
    ) -> None:
        """Send a single message to the connected client.

        This is the sole outbound write path for a connection. The send lock
        serializes every frame so concurrent producers (queue drain, status and
        telemetry loops, crash logs) can never interleave writes on the socket,
        which the websockets library forbids.

        Args:
            message: The message to serialize and send.
            timeout: Optional per-send timeout in seconds.
        """
        client = self.client
        if client is None:
            return

        frame = message.model_dump_json(by_alias=True)
        async with self._send_lock:
            if timeout is None:
                await client.send(frame)
            else:
                await asyncio.wait_for(client.send(frame), timeout)

    async def send_log_now(self, level: LogLevel, message: str) -> None:
        """Send a single log frame directly, ahead of connection teardown.

        Args:
            level: The log level for the frame.
            message: The log message body.
        """
        payload = LogEntry(origin=LogOrigin.FIRMWARE, level=level, message=message)
        try:
            await self.send_frame(
                LogMessage(payload=payload), timeout=CRASH_LOG_SEND_TIMEOUT_S
            )
        except Exception:
            _logger.exception("Failed to send final websocket crash log")

    async def _send_from_queue(self) -> None:
        try:
            while True:
                queued = await get_message_queue().get()
                try:
                    if isinstance(queued, ConfirmedMessage):
                        if queued.sent.cancelled():
                            continue
                        if self.client is None:
                            msg = "No WebSocket client is available for a confirmed message"
                            raise ConnectionError(msg)
                        await self.send_frame(queued.message)
                        if not queued.sent.done():
                            queued.sent.set_result(None)
                    else:
                        await self.send_frame(queued)
                except Exception as e:
                    if isinstance(queued, ConfirmedMessage) and not queued.sent.done():
                        queued.sent.set_exception(e)
                    log_error(f"Error sending queued message: {e}")
        except asyncio.CancelledError:
            pass

    async def _send_status_periodically(self) -> None:
        try:
            while True:
                await self.send_frame(build_status_update(self.state))
                await asyncio.sleep(1 / 2)
        except asyncio.CancelledError:
            pass

    async def _send_telemetry_periodically(self) -> None:
        try:
            while True:
                await self.send_frame(build_telemetry(self.state))
                await asyncio.sleep(1 / 60)
        except asyncio.CancelledError:
            pass

    async def wait_closed(self) -> None:
        """Wait for the server to close."""
        if self.server:
            await self.server.wait_closed()
