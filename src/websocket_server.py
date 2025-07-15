import asyncio
import json
from typing import Optional
import websockets
from websockets.server import WebSocketServer, WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed
from rov_state import ROVState
from websocket_handler import handle_message

event_message_queue: asyncio.Queue = asyncio.Queue()


def get_event_message_queue() -> asyncio.Queue:
    return event_message_queue


class WebsocketServer:
    def __init__(self, state: ROVState) -> None:
        self.state = state
        self.server: Optional[WebSocketServer] = None
        self.client: Optional[WebSocketServerProtocol] = None

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        """Handles a new client connection and updates the global state."""
        self.client = websocket
        self.state.is_client_connected = True
        print(f"Client connected: {websocket.remote_address}. Status: Connected")
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
            self.state.is_client_connected = False
            print("Client disconnected. Status: Not Connected")

    async def start(self, host: str = "10.10.10.10", port: int = 9000) -> None:
        self.server = await websockets.serve(self.handler, host, port)
        print(f"Websocket server started on {host}:{port}")

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
