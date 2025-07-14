import asyncio
import websockets
from websockets.server import WebSocketServer, WebSocketServerProtocol
from typing import Optional
from rov_state import ROVState


class WebsocketServer:
    def __init__(self, state: ROVState) -> None:
        self.state = state
        self.server: Optional[WebSocketServer] = None

    async def handler(self, websocket: WebSocketServerProtocol, path: str) -> None:
        try:
            async for message in websocket:
                await asyncio.sleep(0.01)
        except websockets.ConnectionClosed:
            pass

    async def start(self, host: str = "0.0.0.0", port: int = 9000) -> None:
        self.server = await websockets.serve(self.handler, host, port)
        print(f"Websocket server started on {host}:{port}")

    async def wait_closed(self) -> None:
        if self.server:
            await self.server.wait_closed()
