from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.exceptions import ConnectionClosed
    from .server import WebsocketServer
    from ..rov_state import RovState

import asyncio
import json
from .server import get_message_queue
from .message import Telemetry, RovTelemetry, StatusUpdate, RovStatus


class WebsocketSenders:
    def __init__(self, state: RovState, ws_server: WebsocketServer) -> None:
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
            telemetry_payload = RovTelemetry(
                pitch=self.state.regulator.get("pitch", 0.0),
                roll=self.state.regulator.get("roll", 0.0),
                desired_pitch=self.state.regulator.get("desired_pitch", 0.0),
                desired_roll=self.state.regulator.get("desired_roll", 0.0),
                depth=self.state.pressure.get("depth", 0.0),
                temperature=self.state.pressure.get("temperature", 0.0),
                thruster_rpms=getattr(self.state.thrusters, "erpms", [0] * 8),
            )
            message = Telemetry(payload=telemetry_payload).json(by_alias=True)
            await self._send_message(message)
            await asyncio.sleep(1 / 60)

    async def status_update_sender(self) -> None:
        while True:
            status_update_payload = RovStatus(
                pitch_stabilization=self.state.system_status.pitch_stabilization,
                roll_stabilization=self.state.system_status.roll_stabilization,
                depth_stabilization=self.state.system_status.depth_stabilization,
                battery_percentage=getattr(self.state, "battery_percentage", 0),
            )
            message = StatusUpdate(payload=status_update_payload).json(by_alias=True)
            await self._send_message(message)
            await asyncio.sleep(1 / 2)

    async def message_sender(self) -> None:
        queue = get_message_queue()
        while True:
            message = await queue.get()
            if hasattr(message, "json"):
                message_str = message.json(by_alias=True)
            else:
                message_str = json.dumps(message)
            await self._send_message(message_str)
            queue.task_done()
