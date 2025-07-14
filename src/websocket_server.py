import asyncio
import websockets


class WebsocketServer:
    def __init__(self, state):
        self.state = state
        self.server = None

    async def handler(self, websocket, path):
        # Placeholder: handle incoming websocket connections
        # Message handling will be added later
        try:
            async for message in websocket:
                # No message handling yet
                await asyncio.sleep(0.01)
        except websockets.ConnectionClosed:
            pass

    async def start(self, host="0.0.0.0", port=9000):
        # Start the websocket server
        self.server = await websockets.serve(self.handler, host, port)
        print(f"Websocket server started on {host}:{port}")

    async def wait_closed(self):
        if self.server:
            await self.server.wait_closed()
