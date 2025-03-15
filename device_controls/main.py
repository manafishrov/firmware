import asyncio
import json
import time
import websockets
import logging
from config import get_ip_address, get_device_controls_port

# User made packages
import wetsensor
import thrusters
import imu

# Variables owned by this script
PID_enabled = True
connected = True #Used to disable thrusters when loosing connection
heartbeat_received = True

async def handle_client(websocket):
    logging.info(f"Client connected from Cyberfish App at {websocket.remote_address}!")

    global heartbeat_received

    async def send_heartbeat():
        global heartbeat_received, connected
        while True:
            try:
                if not heartbeat_received:
                    logging.error("Heartbeat not received in 1 second, disabling thrusters")
                    connected = False
                    thrusters.run_thrusters([0, 0, 0, 0, 0, 0], False)

                heartbeat_msg = {
                    "message_type": "Heartbeat",
                    "payload": {
                        "timestamp": int(time.time())
                    }
                }
                await websocket.send(json.dumps(heartbeat_msg))
                logging.info("Sent heartbeat")

                heartbeat_received = False

                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Heartbeat error: {e}")
                break

    async def send_status_updates():
        # THIS IS WHERE WE NEED TO PUT THE CODE TO READ THE WATER SENSOR
        # Preferably we import from another file.

        counter = 0
        while True:
            try:
                if counter % 1 == 0:
                    water_sensor_status = wetsensor.check_sensor(15)
                    status_msg = {
                        "message_type": "Status",
                        "payload": {
                            "water_sensor_status": water_sensor_status
                        }
                    }
                    await websocket.send(json.dumps(status_msg))
                    logging.info(f"Sent status update: water_sensor_status={water_sensor_status}")
                counter += 1
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Status update error: {e}")
                break

    async def update_imu_reading():
        while True:
            try:
                imu.update_pitch_roll()
                await asyncio.sleep(0.01)
            except Exception as e:
                logging.error(f"IMU update error: {e}")

    try:
        heartbeat_task = asyncio.create_task(send_heartbeat())
        status_task = asyncio.create_task(send_status_updates())
        imu_task = asyncio.create_task(update_imu_reading())

        async for message in websocket:
            try:
                msg_data = json.loads(message)
                msg_type = msg_data.get("message_type")
                payload = msg_data.get("payload")

                if msg_type == "Command" and payload == "connect":
                    logging.info("Client sent handshake")

                elif msg_type == "Heartbeat":
                    logging.info("Received heartbeat response")
                    heartbeat_received = True

                elif msg_type == "ControlInput":
                    if isinstance(payload, list) and len(payload) == 6:
                        # HERE WE GET THE INPUT ARRAY FROM THE APP
                        thrusters.run_thrusters(payload, PID_enabled)

                        #logging.info(f"Received control input: {payload}")
                    else:
                        logging.warning(f"Invalid control input format: {payload}")
                else:
                    logging.info(f"Received message: {msg_data}")

            except json.JSONDecodeError:
                logging.warning(f"Received non-JSON message: {message}")

    except websockets.exceptions.ConnectionClosed as e:
        logging.info(f"Client disconnected: {e}")
    finally:
        heartbeat_task.cancel()
        status_task.cancel()
        imu_task.cancel()

async def main(): 
    # INITIALIZING THRUSTERS
    thrusters.initialize_thrusters()
    print("10 second wait for thrusters to initialize starting now...")
    time.sleep(10)
    wetsensor.setup_sensor()

    # INITIALIZING WEBSOCKET SERVER
    try:
        ip_address = get_ip_address()
        port = int(get_device_controls_port())

        server = await websockets.serve(
            handle_client,
            ip_address,
            port
        )

        await server.wait_closed()
    except Exception as e:
        logging.error(f"Server error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
