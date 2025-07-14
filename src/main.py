import asyncio
from rov_state import ROVState
from imu import IMU
from pressure import PressureSensor
from websocket_server import WebsocketServer


async def main() -> None:
    state = ROVState()

    imu = IMU(state)
    pressure_sensor = PressureSensor(state)
    ws_server = WebsocketServer(state)

    await ws_server.start()
    tasks = [
        imu.start_reading_loop(),
        pressure_sensor.start_reading_loop(),
        ws_server.wait_closed(),
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
