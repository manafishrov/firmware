from typing import Optional
from websockets.server import WebSocketServer, WebSocketServerProtocol
import websockets
from rov_state import ROVState
from websocket_handler import handle_message
import json


class WebsocketServer:
    def __init__(self, state: ROVState) -> None:
        self.state = state
        self.server: Optional[WebSocketServer] = None

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    payload = data.get("payload")
                    await handle_message(msg_type, payload, websocket, self.state)
                except Exception as e:
                    print(f"Invalid message or handler error: {e}")
        except Exception as e:
            print(f"WebSocket connection error: {e}")

    async def start(self, host: str = "10.10.10.10", port: int = 9000) -> None:
        self.server = await websockets.serve(self.handler, host, port)
        print(f"Websocket server started on {host}:{port}")

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
