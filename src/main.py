from __future__ import annotations

import asyncio
from .rov_state import RovState
from .thrusters import Thrusters
from .sensors.imu import Imu
from .sensors.pressure import PressureSensor
from .websocket.server import WebsocketServer
from .log import log_info


async def main() -> None:
    state = RovState()
    imu = Imu(state)
    pressure = PressureSensor(state)
    thrusters = Thrusters(state)
    ws_server = WebsocketServer(state)

    await imu.initialize()
    await pressure.initialize()
    await thrusters.initialize()

    thrusters.start_tasks()
    await ws_server.start()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        ws_server.wait_closed(),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(log_info("Starting ROV Firmware..."))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(log_info("Shutting down."))
