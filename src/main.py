"""Main entry point for the ROV firmware."""

from __future__ import annotations

import asyncio

from .log import log_info
from .regulator import Regulator
from .rov_state import RovState
from .sensors.esc import EscSensor
from .sensors.imu import Imu
from .sensors.pressure import PressureSensor
from .serial import SerialManager
from .thrusters import Thrusters
from .websocket.server import WebsocketServer


async def main() -> None:
    """Run the main ROV firmware loop."""
    state: RovState = RovState()
    ws_server: WebsocketServer = WebsocketServer(state)
    serial_manager: SerialManager = SerialManager(state)
    imu: Imu = Imu(state)
    pressure: PressureSensor = PressureSensor(state)
    regulator: Regulator = Regulator(state)
    esc: EscSensor = EscSensor(state, serial_manager)
    thrusters: Thrusters = Thrusters(state, serial_manager, regulator)

    await ws_server.initialize()
    await serial_manager.initialize()
    await imu.initialize()
    await pressure.initialize()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        esc.read_loop(),
        thrusters.send_loop(),
        ws_server.wait_closed(),
    ]
    _ = await asyncio.gather(*tasks)

    await serial_manager.shutdown()


if __name__ == "__main__":
    log_info("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Shutting down.")
