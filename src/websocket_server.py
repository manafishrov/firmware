from __future__ import annotations
import asyncio
import json
import websockets
from websockets.exceptions import ConnectionClosed
from websocket_handler import handle_message
from log import set_log_is_client_connected_status, log_info, log_error, log_warn
from typing import Optional
from websockets.server import WebSocketServer, WebSocketServerProtocol
from rov_state import ROVState

FIRMWARE_VERSION = "1.0.0"
IP_ADDRESS = "10.10.10.10"
PORT = 9000

message_queue: asyncio.Queue = asyncio.Queue()


def get_message_queue() -> asyncio.Queue:
    return message_queue


class WebsocketServer:
    def __init__(self, state: ROVState) -> None:
        self.state = state
        self.server: Optional[WebSocketServer] = None
        self.client: Optional[WebSocketServerProtocol] = None

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        self.client = websocket
        set_log_is_client_connected_status(True)
        await log_info(f"Client connected: {websocket.remote_address}.")

        async def send_firmware_version_on_connect():
            await asyncio.sleep(5)
            try:
                version_message = {
                    "type": "firmwareVersion",
                    "payload": FIRMWARE_VERSION,
                }
                await websocket.send(json.dumps(version_message))
                await log_info(
                    f"Sent firmware version '{FIRMWARE_VERSION}' to {websocket.remote_address}"
                )
                config_message = {
                    "type": "config",
                    "payload": self.state.rov_config,
                }
                await websocket.send(json.dumps(config_message))
                await log_info(f"Sent config to {websocket.remote_address}")
            except ConnectionClosed:
                await log_warn(
                    f"Client disconnected before firmware version and config could be sent to {websocket.remote_address}"
                )
            except Exception as e:
                await log_error(f"Error sending initial data: {e}")

        asyncio.create_task(send_firmware_version_on_connect())

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    payload = data.get("payload")
                    await handle_message(msg_type, payload, websocket, self.state)
                except json.JSONDecodeError:
                    await log_error(
                        f"Error: Received invalid JSON from {websocket.remote_address}"
                    )
                except Exception as e:
                    await log_error(f"Error processing message: {e}")
        except ConnectionClosed:
            await log_info(f"Client connection closed: {websocket.remote_address}")
        finally:
            self.client = None
            set_log_is_client_connected_status(False)
            await log_info("Client disconnected.")

    async def start(self) -> None:
        self.server = await websockets.serve(self.handler, IP_ADDRESS, PORT)
        await log_info(f"Websocket server started on {IP_ADDRESS}:{PORT}")

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
