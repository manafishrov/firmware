from __future__ import annotations
import asyncio
import json
from websocket_server import WebsocketServer, get_message_queue
from websockets.exceptions import ConnectionClosed
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
            message = json.dumps(
                {
                    "type": "telemetry",
                    "payload": {
                        "pitch": self.state.regulator["pitch"],
                        "roll": self.state.regulator["roll"],
                        "desiredPitch": self.state.regulator["desiredPitch"],
                        "desiredRoll": self.state.regulator["desiredRoll"],
                        "depth": self.state.pressure["depth"],
                        "temperature": self.state.pressure["temperature"],
                        "thrusterErpms": self.state.thrusters.erpms,
                    },
                }
            )
            await self._send_message(message)
            await asyncio.sleep(1 / 60)

    async def status_update_sender(self) -> None:
        while True:
            status_data = {
                "pitchStabilization": self.state.pitch_stabilization,
                "rollStabilization": self.state.roll_stabilization,
                "depthStabilization": self.state.depth_stabilization,
                "batteryPercentage": self.state.battery_percentage,
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
