import asyncio
import json
import time
import websockets
import logging
import math
import random
import signal

logging.basicConfig(level=logging.INFO)

clients = set()
shutdown = False


async def handle_client(websocket):
    logging.info(f"Client connected from Manafish App at {websocket.remote_address}!")
    clients.add(websocket)

    async def send_heartbeat():
        while not shutdown:
            try:
                heartbeat_msg = {
                    "message_type": "Heartbeat",
                    "payload": {"timestamp": int(time.time())},
                }
                await websocket.send(json.dumps(heartbeat_msg))
                logging.debug("Sent heartbeat")
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Heartbeat error: {e}")
                break

    async def send_status_updates():
        while not shutdown:
            try:
                current_time = time.time()

                pitch = 45 * math.sin(current_time / 2) + random.uniform(-5, 5)
                roll = 30 * math.cos(current_time / 3) + random.uniform(-5, 5)
                desired_pitch = 20 * math.sin(current_time / 4)
                desired_roll = 15 * math.cos(current_time / 5)

                water_detected = (int(current_time) % 10) < 5

                status_msg = {
                    "message_type": "Status",
                    "payload": {
                        "water_detected": water_detected,
                        "pitch": round(pitch, 2),
                        "roll": round(roll, 2),
                        "desired_pitch": round(desired_pitch, 2),
                        "desired_roll": round(desired_roll, 2),
                    },
                }
                await websocket.send(json.dumps(status_msg))
                await asyncio.sleep(1 / 60)
            except Exception as e:
                if not shutdown:
                    logging.error(f"Status update error: {e}")
                break

    heartbeat_task = asyncio.create_task(send_heartbeat())
    status_task = asyncio.create_task(send_status_updates())

    try:
        async for message in websocket:
            if shutdown:
                break
            try:
                msg_data = json.loads(message)
                msg_type = msg_data.get("message_type")
                payload = msg_data.get("payload")

                if msg_type == "Command" and payload == "connect":
                    logging.info("Client sent handshake")
                elif msg_type == "Heartbeat":
                    logging.debug("Received heartbeat response")
                elif msg_type == "ControlInput":
                    if isinstance(payload, list) and len(payload) == 6:
                        logging.info(f"Received control input: {payload}")
                    else:
                        logging.warning(f"Invalid control input format: {payload}")
                else:
                    logging.info(f"Received message: {msg_data}")
            except json.JSONDecodeError:
                logging.warning(f"Received non-JSON message: {message}")

    except websockets.exceptions.ConnectionClosed as e:
        if not shutdown:
            logging.info(f"Client disconnected: {e}")
    finally:
        clients.remove(websocket)
        heartbeat_task.cancel()
        status_task.cancel()


async def shutdown_server(server):
    global shutdown
    shutdown = True
    if clients:
        logging.info("Closing client connections...")
        await asyncio.gather(*(ws.close() for ws in clients))
    logging.info("Stopping server...")
    server.close()
    await server.wait_closed()


async def main():
    server = None
    shutdown_event = asyncio.Event()

    def signal_handler():
        logging.info("Shutdown signal received")
        shutdown_event.set()

    try:
        server = await websockets.serve(handle_client, "10.10.10.10", 9000)
        logging.info("Mock server running on 10.10.10.10:9000")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        await shutdown_event.wait()
        await shutdown_server(server)
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        if server and not shutdown:
            await shutdown_server(server)
        logging.info("Server shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Exiting...")
