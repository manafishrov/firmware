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

async def handle_client(websocket):
    logging.info(f"Client connected from Cyberfish App at {websocket.remote_address}!")

    async def send_heartbeat():
        while True:
            try:

                heartbeat_msg = {
                    "message_type": "Heartbeat",
                    "payload": {
                        "timestamp": int(time.time())
                    }
                }
                await websocket.send(json.dumps(heartbeat_msg))
                logging.info("Sent heartbeat")

                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Heartbeat error: {e}")
                break

    # async def send_status_updates():
    #     counter = 0
    #     while True:
    #         try:
    #             if counter % 1 == 0:
    #                 water_sensor_status = wetsensor.check_sensor(15)
    #                 status_msg = {
    #                     "message_type": "Status",
    #                     "payload": {
    #                         "water_sensor_status": water_sensor_status
    #                     }
    #                 }
    #                 await websocket.send(json.dumps(status_msg))
    #                 #logging.info(f"Sent status update: water_sensor_status={water_sensor_status}")
    #             counter += 1
    #             await asyncio.sleep(1)
    #         except Exception as e:
    #             logging.error(f"Status update error: {e}")
    #             break

    async def update_imu_reading():
        while True:
            try:
                imu.update_pitch_roll()
                await asyncio.sleep(0.1) ## HAS TO CHANGE LATER
            except Exception as e:
                logging.error(f"IMU update error: {e}")
                await asyncio.sleep(3)
            

    try:
        heartbeat_task = asyncio.create_task(send_heartbeat())
        #status_task = asyncio.create_task(send_status_updates())
        imu_task = asyncio.create_task(update_imu_reading())

        messageNr = 0 #This is the MOST MAKESHIFTED THING EVER, BUT IT WORKS FOR NOW
        async for message in websocket:
            messageNr += 1
            if messageNr % 4 == 0:
                try:
                    msg_data = json.loads(message)
                    msg_type = msg_data.get("message_type")
                    payload = msg_data.get("payload")

                    if msg_type == "Command" and payload == "connect":
                        logging.info("Client sent handshake")

                    elif msg_type == "Heartbeat":
                        logging.info("Received heartbeat response")
                        logging.info(f"Pitch: {imu.current_pitch}, Roll: {imu.current_roll}")


                    elif msg_type == "ControlInput":
                        if isinstance(payload, list) and len(payload) == 6:
                            # HERE WE GET THE INPUT ARRAY FROM THE APP
                            thrusters.run_thrusters(payload, PID_enabled=False)

                            logging.info(f"Received control input: {payload}")
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
        #status_task.cancel()
        imu_task.cancel()

async def main(): 
    # Trying to initialize the IMU sensor, if it fails, throw an error and continue
    try:
        imu.init_sensor()
    except Exception as e:
        logging.error(f"IMU setup error: {e}")

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
