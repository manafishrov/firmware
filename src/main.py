from __future__ import annotations

import asyncio
from .rov_state import RovState
from .thrusters import Thrusters
from .sensors.imu import Imu
from .sensors.pressure import PressureSensor
from .sensors.esc import EscSensor
from .serial import SerialManager
from .websocket.server import WebsocketServer
from .regulator import Regulator
from .log import log_info


async def main() -> None:
    state: RovState = RovState()
    serial_manager: SerialManager = SerialManager(state)
    await serial_manager.initialize()

    regulator: Regulator = Regulator(state)
    imu: Imu = Imu(state)
    pressure: PressureSensor = PressureSensor(state)
    esc: EscSensor = EscSensor(state, serial_manager)
    ws_server: WebsocketServer = WebsocketServer(state)
    thrusters: Thrusters = Thrusters(state, serial_manager, regulator, ws_server)

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
    log_info("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        log_info("Shutting down.")
