from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.exceptions import ConnectionClosed
    from websockets.server import WebSocketServer, WebSocketServerProtocol
    from rov_state import RovState

import asyncio
import json
import websockets
from ..websocket.handler import handle_message
from ..websocket.send.config import handle_send_firmware_version, handle_send_config
from ..log import set_log_is_client_connected_status, log_info, log_error, log_warn
from .message import WebsocketMessage

FIRMWARE_VERSION = "1.0.0"
IP_ADDRESS = "10.10.10.10"
PORT = 9000

message_queue: asyncio.Queue = asyncio.Queue()


def get_message_queue() -> asyncio.Queue:
    return message_queue


class WebsocketServer:
    def __init__(self, state: RovState) -> None:
        self.state = state
        self.server: Optional[WebSocketServer] = None
        self.client: Optional[WebSocketServerProtocol] = None

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        self.client = websocket
        set_log_is_client_connected_status(True)
        log_info(f"Client connected: {websocket.remote_address}.")

        send_task = asyncio.create_task(self._send_from_queue(websocket))
        status_task = asyncio.create_task(
            self._send_status_periodically(websocket, self.state)
        )
        telemetry_task = asyncio.create_task(
            self._send_telemetry_periodically(websocket, self.state)
        )

        async def send_firmware_version_on_connect():
            await asyncio.sleep(5)
            try:
                await handle_send_firmware_version(websocket)
                log_info(
                    f"Sent firmware version '{FIRMWARE_VERSION}' to {websocket.remote_address}"
                )
                await handle_send_config(websocket, self.state)
                log_info(f"Sent config to {websocket.remote_address}")
            except ConnectionClosed:
                log_warn(
                    f"Client disconnected before firmware version and config could be sent to {websocket.remote_address}"
                )
            except Exception as e:
                log_error(f"Error sending initial data: {e}")

        asyncio.create_task(send_firmware_version_on_connect())

        try:
            for message in websocket:
                try:
                    data = json.loads(message)
                    deserialized_msg = WebsocketMessage(**data)
                    await handle_message(self.state, websocket, deserialized_msg)
                except json.JSONDecodeError:
                    log_error(
                        f"Error: Received invalid JSON from {websocket.remote_address}"
                    )
                except Exception as e:
                    log_error(f"Error processing message: {e}")
        except ConnectionClosed:
            log_info(f"Client connection closed: {websocket.remote_address}")
        finally:
            send_task.cancel()
            status_task.cancel()
            telemetry_task.cancel()
            self.client = None
            set_log_is_client_connected_status(False)
            log_info("Client disconnected.")

    async def start(self) -> None:
        self.server = await websockets.serve(self.handler, IP_ADDRESS, PORT)
        log_info(f"Websocket server started on {IP_ADDRESS}:{PORT}")

    async def _send_from_queue(self, websocket: WebSocketServerProtocol) -> None:
        try:
            while True:
                message = await message_queue.get()
                try:
                    json_msg = message.json(by_alias=True)
                    await websocket.send(json_msg)
                except Exception as e:
                    log_error(f"Error sending queued message: {e}")
        except asyncio.CancelledError:
            pass

    async def _send_status_periodically(
        self, websocket: WebSocketServerProtocol, state
    ) -> None:
        from .send.status import handle_status_update

        try:
            while True:
                await handle_status_update(websocket, state)
                await asyncio.sleep(1 / 2)
        except asyncio.CancelledError:
            pass

    async def _send_telemetry_periodically(
        self, websocket: WebSocketServerProtocol, state
    ) -> None:
        from .send.telemetry import handle_telemetry

        try:
            while True:
                await handle_telemetry(websocket, state)
                await asyncio.sleep(1 / 60)
        except asyncio.CancelledError:
            pass

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
