from __future__ import annotations

import asyncio
import time
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
    thrusters: Thrusters = Thrusters(state, serial_manager, regulator)
    ws_server: WebsocketServer = WebsocketServer(state)

    async def health_check(state: RovState) -> None:
        while True:
            now = time.time()
            if state.imu.measured_at and now - state.imu.measured_at > 0.5:
                state.system_health.imu_ok = False
            if state.pressure.measured_at and now - state.pressure.measured_at > 1:
                state.system_health.pressure_sensor_ok = False
            await asyncio.sleep(1)

    await imu.initialize()
    await pressure.initialize()

    await ws_server.start()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        esc.read_loop(),
        thrusters.send_loop(),
        health_check(state),
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
