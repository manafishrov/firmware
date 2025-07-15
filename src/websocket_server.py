import asyncio
import json
from typing import Optional
import websockets
from websockets.server import WebSocketServer, WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed
from rov_state import ROVState
from websocket_handler import handle_message
from log import set_log_is_client_connected_status

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
        print(f"Client connected: {websocket.remote_address}. Status: Connected")

        async def send_firmware_version_on_connect():
            await asyncio.sleep(5)
            if websocket.open:
                try:
                    version_message = {
                        "type": "firmwareVersion",
                        "payload": FIRMWARE_VERSION,
                    }
                    await websocket.send(json.dumps(version_message))
                    print(
                        f"Sent firmware version '{FIRMWARE_VERSION}' to {websocket.remote_address}"
                    )
                    config_message = {
                        "type": "config",
                        "payload": self.state.rov_config,
                    }
                    await websocket.send(json.dumps(config_message))
                    print(f"Sent config to {websocket.remote_address}")
                except ConnectionClosed:
                    print(
                        f"Client disconnected before firmware version could be sent to {websocket.remote_address}"
                    )
                except Exception as e:
                    print(f"Error sending firmware version: {e}")

        asyncio.create_task(send_firmware_version_on_connect())

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    payload = data.get("payload")
                    await handle_message(msg_type, payload, websocket, self.state)
                except json.JSONDecodeError:
                    print(
                        f"Error: Received invalid JSON from {websocket.remote_address}"
                    )
                except Exception as e:
                    print(f"Error processing message: {e}")
        except ConnectionClosed:
            print(f"Client connection closed: {websocket.remote_address}")
        finally:
            self.client = None
            set_log_is_client_connected_status(False)
            print("Client disconnected. Status: Not Connected")

    async def start(self) -> None:
        self.server = await websockets.serve(self.handler, IP_ADDRESS, PORT)
        print(f"Websocket server started on {IP_ADDRESS}:{PORT}")

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
