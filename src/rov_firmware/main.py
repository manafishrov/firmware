"""Main entry point for the ROV firmware."""

import asyncio

from serial import SerialException

from .firmware_update import HttpUpdateServer
from .regulator import Regulator
from .rov_state import RovState
from .sensors.imu import Imu
from .sensors.mcu import McuSensor
from .sensors.pressure import PressureSensor
from .serial import SerialManager
from .thrusters import Thrusters
from .websocket.server import WebsocketServer


def _exception_handler(
    loop: asyncio.AbstractEventLoop, context: dict[str, object]
) -> None:
    exception = context.get("exception")
    if isinstance(exception, SerialException):
        return
    loop.default_exception_handler(context)


async def main() -> None:
    """Run the main ROV firmware loop."""
    asyncio.get_running_loop().set_exception_handler(_exception_handler)

    state: RovState = RovState()
    ws_server: WebsocketServer = WebsocketServer(state)
    http_update_server: HttpUpdateServer = HttpUpdateServer(state)
    serial_manager: SerialManager = SerialManager(state)
    imu: Imu = Imu(state)
    pressure: PressureSensor = PressureSensor(state)
    regulator: Regulator = Regulator(state)
    mcu: McuSensor = McuSensor(state, serial_manager)
    thrusters: Thrusters = Thrusters(state, serial_manager, regulator)

    await ws_server.initialize()
    await http_update_server.initialize()
    _ = await serial_manager.initialize()
    await imu.initialize()
    await pressure.initialize()

    tasks = [
        imu.read_loop(),
        pressure.read_loop(),
        mcu.read_loop(),
        thrusters.send_loop(),
        ws_server.wait_closed(),
        http_update_server.wait_closed(),
        http_update_server.watch_status_loop(),
    ]
    _ = await asyncio.gather(*tasks)

    await serial_manager.shutdown()
