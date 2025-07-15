import asyncio
from rov_state import ROVState
from imu import IMU
from pressure import PressureSensor
from websocket_server import WebsocketServer
from websocket_senders import WebsocketSenders


async def main() -> None:
    state = ROVState()
    ws_server = WebsocketServer(state)
    senders = WebsocketSenders(state, ws_server)

    await ws_server.start()
    message_sender_task = asyncio.create_task(senders.message_sender())

    imu = IMU(state)
    pressure_sensor = PressureSensor(state)

    tasks = [
        imu.start_reading_loop(),
        pressure_sensor.start_reading_loop(),
        ws_server.wait_closed(),
        senders.telemetry_sender(),
        senders.status_update_sender(),
        message_sender_task,
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    print("Starting ROV Firmware...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down.")
