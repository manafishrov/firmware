"""WebSocket server for the ROV firmware."""

import asyncio
import json
import logging
import os
from pathlib import Path
import time
from typing import cast

from pydantic import TypeAdapter
import websockets
from websockets import Server, ServerConnection
from websockets.exceptions import ConnectionClosed

from ..constants import CRASH_LOG_SEND_TIMEOUT_S
from ..extensions.api import dispatch
from ..extensions.runtime import ExtensionRuntime
from ..extensions.wire import (
    CapabilityCatalog,
    CapabilityRequest,
    CapabilityResponse,
    CapabilitySamples,
)
from ..log import (
    flush_pending_logs,
    get_local_logger,
    log_error,
    log_info,
    log_warn,
    stamp_log_message,
)
from ..models.log import LogEntry, LogLevel, LogOrigin
from ..rov_state import RovState
from ..serial import SerialManager
from .handler import handle_message
from .message import LogMessage, WebsocketMessage
from .queue import ConfirmedMessage, get_message_queue
from .receive.config import reject_invalid_config_message
from .send.config import build_config
from .state import websocket_state


MAX_CONCURRENT_REQUESTS = 64

_logger = get_local_logger()

websocket_message_adapter = TypeAdapter(WebsocketMessage)


class WebsocketServer:
    """WebSocket server class."""

    def __init__(self, state: RovState, serial_manager: SerialManager) -> None:
        """Initialize the WebSocket server.

        Args:
            state: The ROV state.
            serial_manager: The MCU serial connection used for ESC updates.
        """
        self.capabilities = ExtensionRuntime(
            state,
            Path(
                os.environ.get(
                    "MANAFISH_DATA_DIR",
                    str(Path.home() / ".local" / "share" / "manafish"),
                )
            )
            / "extensions",
        )
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
        if self.client is not None:
            await websocket.close(code=1008, reason="Another operator is connected")
            return
        self.client = websocket
        websocket_state.is_client_connected = True
        websocket_state.connection_generation += 1
        log_info(
            f"Client connected: {cast(tuple[str, int] | None, websocket.remote_address)}."
        )

        send_task = asyncio.create_task(self._send_from_queue())
        telemetry_task: asyncio.Task[None] | None = None
        requests: set[asyncio.Task[None]] = set()
        try:
            await flush_pending_logs()
            await self.send_frame(build_config(self.state))
            log_info(
                f"Sent config to {cast(tuple[str, int] | None, websocket.remote_address)}"
            )
            await self.capabilities.connected()
            await self.send_frame(
                CapabilityCatalog(payload=self.capabilities.catalog())
            )
            telemetry_task = asyncio.create_task(self._send_capabilities_periodically())

            async for message in websocket:
                data: object = None
                try:
                    data = json.loads(message)
                    deserialized_msg = websocket_message_adapter.validate_python(data)
                    if isinstance(deserialized_msg, CapabilityRequest):
                        await self._schedule_capability(deserialized_msg, requests)
                    else:
                        await handle_message(
                            self.state, self.serial_manager, deserialized_msg
                        )
                except json.JSONDecodeError:
                    log_warn(
                        f"Failed to deserialize message from {cast(tuple[str, int] | None, websocket.remote_address)}"
                    )
                except Exception as e:
                    log_warn(f"Error processing message: {e}")
                    await reject_invalid_config_message(self.state, data, str(e))
                    await self._reject_capability(data, str(e))
        except ConnectionClosed:
            log_info(
                f"Client connection closed: {cast(tuple[str, int] | None, websocket.remote_address)}"
            )
        except Exception:
            _logger.exception("WebSocket connection handler failed")
        finally:
            tasks = [send_task, *requests]
            if telemetry_task is not None:
                tasks.append(telemetry_task)
            for task in tasks:
                _ = task.cancel()
            _ = await asyncio.gather(*tasks, return_exceptions=True)
            websocket_state.is_client_connected = False
            await self.capabilities.disconnected()
            self.client = None
            log_info("Client disconnected.")

    async def initialize(self) -> None:
        """Initialize the WebSocket server."""
        await self.capabilities.initialize()
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
        message = stamp_log_message(message)
        _logger.log(
            {
                LogLevel.INFO: logging.INFO,
                LogLevel.WARN: logging.WARNING,
                LogLevel.ERROR: logging.ERROR,
            }[level],
            message,
        )
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

    async def _schedule_capability(
        self, message: CapabilityRequest, requests: set[asyncio.Task[None]]
    ) -> None:
        if len(requests) >= MAX_CONCURRENT_REQUESTS:
            await self._reject_capability(
                message.model_dump(by_alias=True), "Too many pending requests"
            )
            return
        task = asyncio.create_task(self._handle_capability(message))
        requests.add(task)

        def completed(finished: asyncio.Task[None]) -> None:
            requests.discard(finished)
            if not finished.cancelled() and (error := finished.exception()) is not None:
                log_warn(f"Capability request failed to complete: {error}")

        task.add_done_callback(completed)

    async def _reject_capability(self, data: object, reason: str) -> None:
        if not isinstance(data, dict):
            return
        envelope = cast(dict[str, object], data)
        if envelope.get("type") != "capabilityRequest":
            return
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return
        fields = cast(dict[str, object], payload)
        if not isinstance(fields.get("requestId"), str):
            return
        await self.send_frame(
            CapabilityResponse(
                payload={
                    "version": 1,
                    "requestId": fields["requestId"],
                    "ok": False,
                    "error": {"code": "invalid_request", "message": reason},
                }
            )
        )

    async def _handle_capability(self, message: CapabilityRequest) -> None:
        payload: dict[str, object] = {
            "version": 1,
            "requestId": message.payload.request_id,
        }
        try:
            result = await dispatch(
                self.capabilities, message.payload.operation, message.payload.params
            )
            payload.update({"ok": True, "result": result})
        except Exception as error:
            log_warn(f"Capability {message.payload.operation}: {error}")
            payload.update(
                {
                    "ok": False,
                    "error": {"code": "operation_failed", "message": str(error)},
                }
            )
        await self.send_frame(CapabilityResponse(payload=payload))

    async def _send_capabilities_periodically(self) -> None:
        period = 1 / 60
        deadline = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now >= deadline + period:
                    deadline = now
                self.capabilities.refresh_builtins()
                if self.capabilities.catalog_changed:
                    self.capabilities.catalog_changed = False
                    await self.send_frame(
                        CapabilityCatalog(payload=self.capabilities.catalog())
                    )
                events = list(self.capabilities.events)
                self.capabilities.events.clear()
                if events:
                    await self.send_frame(
                        CapabilitySamples(
                            payload={
                                "version": 1,
                                "samples": [
                                    sample.model_dump(by_alias=True)
                                    for sample in events
                                ],
                            }
                        )
                    )
                deadline = max(time.monotonic(), deadline + period)
                await asyncio.sleep(max(0.0, deadline - time.monotonic()))
        except asyncio.CancelledError:
            pass

    async def wait_closed(self) -> None:
        """Wait for the server to close."""
        if self.server:
            await self.server.wait_closed()
