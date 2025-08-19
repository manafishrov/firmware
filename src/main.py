from __future__ import annotations

import asyncio
from rov_state import ROVState
from imu import IMU
from pressure import PressureSensor
from websocket_server import WebsocketServer
from websocket_senders import WebsocketSenders
from log import log_info


async def main() -> None:
    state = ROVState()
    ws_server = WebsocketServer(state)
    senders = WebsocketSenders(state, ws_server)

    await ws_server.start()
    message_sender_task = asyncio.create_task(senders.message_sender())

    # imu = IMU(state)
    # await imu.initialize()
    # pressure_sensor = PressureSensor(state)
    # await pressure_sensor.initialize()
    await state.thrusters.initialize()

    tasks = [
        # imu.start_reading_loop(),
        # pressure_sensor.start_reading_loop(),
        ws_server.wait_closed(),
        senders.telemetry_sender(),
        senders.status_update_sender(),
        message_sender_task,
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
