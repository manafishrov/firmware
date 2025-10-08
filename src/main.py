from __future__ import annotations

import asyncio
from .rov_state import RovState
from .thrusters import Thrusters
from .sensors.imu import Imu
from .sensors.pressure import PressureSensor
from .sensors.esc import EscSensor
from .websocket.server import WebsocketServer
from .log import log_info


async def main() -> None:
    state = RovState()
    imu = Imu(state)
    pressure = PressureSensor(state)
    esc = EscSensor(state)
    thrusters = Thrusters(state, esc.serial)
    ws_server = WebsocketServer(state)

    await imu.initialize()
    await pressure.initialize()
    await esc.initialize()

    await ws_server.start()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        esc.read_loop(),
        thrusters.send_loop(),
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
