import asyncio
import json
import time
import websockets
import logging
from config import get_ip_address, get_device_controls_port

from imu import IMU
from thrusters import ThrusterController

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Instantiate IMU sensor and Thruster controller
imu_sensor = IMU()
thruster_ctrl = ThrusterController(imu_sensor)


async def handle_client(websocket):
    logging.info(f"Client connected from Cyberfish App at {websocket.remote_address}!")

    async def send_heartbeat():
        while True:
            try:
                heartbeat_msg = {
                    "message_type": "Heartbeat",
                    "payload": {"timestamp": int(time.time())},
                }
                await websocket.send(json.dumps(heartbeat_msg))
                logging.info("Sent heartbeat")
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Heartbeat error: {e}")
                break

    async def send_status_updates():
        counter = 0
        while True:
            try:
                if counter % 1 == 0:
                    desired_pitch, desired_roll = thruster_ctrl.get_desired_pitch_roll()
                    status_msg = {
                        "message_type": "Status",
                        "payload": {
                            "pitch": imu_sensor.current_pitch,
                            "roll": imu_sensor.current_roll,
                            "desired_pitch": desired_pitch,
                            "desired_roll": desired_roll,
                            "water_detected": False,
                        },
                    }
                    await websocket.send(json.dumps(status_msg))
                counter += 1
                await asyncio.sleep(0.1)

            except Exception as e:
                logging.error(f"Status update error: {e}")
                break

    async def update_imu_reading():
        while True:
            try:
                imu_sensor.update_pitch_roll()
                await asyncio.sleep(0.05)
            except Exception as e:
                logging.error(f"IMU update error: {e}")
                await asyncio.sleep(3)

    heartbeat_task = asyncio.create_task(send_heartbeat())
    status_task = asyncio.create_task(send_status_updates())
    imu_task = asyncio.create_task(update_imu_reading())

    try:
        messageNr = 0  # the WORST fix but it seems to be necessary, cuts out 3/4 of the messages
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
                        logging.info(
                            f"Pitch: {imu_sensor.current_pitch}, Roll: {imu_sensor.current_roll}"
                        )

                    elif msg_type == "ControlInput":
                        if isinstance(payload, list) and len(payload) == 6:                         
                            thruster_ctrl.run_thrusters(payload)
                            
                            if not thruster_ctrl.PID_enabled and messageNr < 300: # THIS WILL BE REMOVED WHEN WE HAVE THE OPTION TO ENABLE PID IN APP
                                logging.info(f"ENABLING PID CONTROL (300 messages received)")
                                thruster_ctrl.PID_enabled = True

                            # logging.info(f"Received control input: {payload}")
                        else:
                            logging.warning(f"Invalid control input format: {payload}")

                    elif msg_type == "Setting":
                        if payload == "enable_PID":
                            thruster_ctrl.PID_enabled = True
                            logging.info("PID control enabled")
                        elif payload == "disable_PID":
                            thruster_ctrl.PID_enabled = False
                            logging.info("PID control disabled")
                        else:
                            logging.warning(f"Unknown setting: {payload}")

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
    try:
        ip_address = get_ip_address()
        port = int(get_device_controls_port())
        server = await websockets.serve(handle_client, ip_address, port)
        logging.info(f"Server running on {ip_address}:{port}")
        await server.wait_closed()
    except Exception as e:
        logging.error(f"Server error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
