from __future__ import annotations

import asyncio
from .rov_state import RovState
from .thrusters import Thrusters
from .sensors.imu import Imu
from .sensors.pressure import PressureSensor
from .sensors.esc import EscSensor
from .serial import SerialManager
from .websocket.server import WebsocketServer
from .log import log_info


async def main() -> None:
    state = RovState()
    serial_manager = SerialManager()
    await serial_manager.initialize()

    imu = Imu(state)
    pressure = PressureSensor(state)
    esc = EscSensor(state, serial_manager)
    thrusters = Thrusters(state, serial_manager)
    ws_server = WebsocketServer(state)

    await imu.initialize()
    await pressure.initialize()

    await ws_server.start()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        esc.read_loop(),
        thrusters.send_loop(),
        ws_server.wait_closed(),
    ]
    await asyncio.gather(*tasks)

    await serial_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(log_info("Starting ROV Firmware..."))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(log_info("Shutting down."))
