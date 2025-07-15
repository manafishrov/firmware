import asyncio
import json
from websockets.exceptions import ConnectionClosed
from websocket_server import WebsocketServer, get_message_queue
from rov_state import ROVState


class WebsocketSenders:
    def __init__(self, state: ROVState, ws_server: WebsocketServer) -> None:
        self.state = state
        self.ws_server = ws_server

    async def _send_message(self, message: str) -> None:
        if self.ws_server.client:
            try:
                await self.ws_server.client.send(message)
            except ConnectionClosed:
                pass

    async def telemetry_sender(self) -> None:
        while True:
            telemetry_data = {
                "imu": self.state.imu,
            }
            message = json.dumps({"type": "telemetry", "payload": telemetry_data})
            await self._send_message(message)
            await asyncio.sleep(1 / 60)

    async def status_update_sender(self) -> None:
        while True:
            status_data = {
                "depth": self.state.pressure.depth,
                "temperature": self.state.pressure.temperature,
            }
            message = json.dumps({"type": "statusUpdate", "payload": status_data})
            await self._send_message(message)
            await asyncio.sleep(1 / 2)

    async def message_sender(self) -> None:
        queue = get_message_queue()
        while True:
            message_dict = await queue.get()
            message_str = json.dumps(message_dict)
            await self._send_message(message_str)
            queue.task_done()
