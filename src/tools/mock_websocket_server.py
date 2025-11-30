"""This script mocks the websocket server for testing websocket connections."""

import argparse
import asyncio
import json
import logging
import math
import time
from typing import Any, cast

import websockets
from websockets import ServerConnection


PORT = 9000
FIRMWARE_VERSION = "1.0.0"
MOCK_CONFIG = {
    "microcontrollerFirmwareVariant": "dshot",
    "fluidType": "saltwater",
    "thrusterPinSetup": {
        "identifiers": [0, 1, 2, 3, 4, 5, 6, 7],
        "spinDirections": [1, 1, 1, 1, 1, 1, 1, 1],
    },
    "thrusterAllocation": [
        [1.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0],
        [1.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 1.0, 0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -1.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -1.0, 0.0, -1.0, 0.0, 0.0],
        [-1.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        [-1.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0],
    ],
    "regulator": {
        "turnSpeed": 40,
        "pitch": {"kp": 5, "ki": 0.5, "kd": 1},
        "roll": {"kp": 1.5, "ki": 0.1, "kd": 0.4},
        "depth": {"kp": 0, "ki": 0.05, "kd": 0.1},
    },
    "directionCoefficients": {
        "surge": 0.8,
        "sway": 0.35,
        "heave": 0.5,
        "pitch": 0.4,
        "yaw": 0.3,
        "roll": 0.8,
    },
    "power": {
        "userMaxPower": 30,
        "regulatorMaxPower": 30,
        "batteryMinVoltage": 9.6,
        "batteryMaxVoltage": 12.6,
    },
}

SYSTEM_STATUS = {
    "pitch_stabilization": False,
    "roll_stabilization": False,
    "depth_hold": False,
}


async def _handle_client(websocket: ServerConnection) -> None:  # noqa: C901,PLR0912,PLR0915
    """Handle a websocket client connection."""
    global MOCK_CONFIG  # noqa: PLW0603
    logger = logging.getLogger(__name__)
    logger.info(
        f"Client connected: {cast(tuple[str, int] | None, websocket.remote_address)}"
    )

    async def send_telemetry() -> None:
        """Send mock telemetry data periodically."""
        while True:
            current_time = time.time()
            pitch = 20 * math.sin(current_time / 2)
            roll = 15 * math.cos(current_time / 3)
            desired_pitch = 25 * math.sin(current_time / 2)
            desired_roll = 20 * math.cos(current_time / 3)
            depth = 10 + 5 * math.sin(current_time / 4)
            water_temperature = 20 + 5 * math.cos(current_time / 5)
            electronics_temperature = 25 + 3 * math.sin(current_time / 6)
            thruster_rpms = [
                int(1000 + 500 * math.sin(current_time + i)) for i in range(8)
            ]
            work_indicator_percentage = 50 + 30 * math.sin(current_time / 10)

            telemetry_msg = {
                "type": "telemetry",
                "payload": {
                    "pitch": round(pitch, 2),
                    "roll": round(roll, 2),
                    "desiredPitch": round(desired_pitch, 2),
                    "desiredRoll": round(desired_roll, 2),
                    "depth": round(depth, 2),
                    "waterTemperature": round(water_temperature, 2),
                    "electronicsTemperature": round(electronics_temperature, 2),
                    "thrusterRpms": thruster_rpms,
                    "workIndicatorPercentage": int(work_indicator_percentage),
                },
            }
            try:
                await websocket.send(json.dumps(telemetry_msg))
            except Exception:
                break
            await asyncio.sleep(1 / 60)

    async def send_status() -> None:
        """Send mock status data periodically."""
        while True:
            current_time = time.time()
            battery_percentage = int((math.sin(current_time / 5) + 1) * 50)

            status_msg = {
                "type": "statusUpdate",
                "payload": {
                    "pitchStabilization": SYSTEM_STATUS["pitch_stabilization"],
                    "rollStabilization": SYSTEM_STATUS["roll_stabilization"],
                    "depthHold": SYSTEM_STATUS["depth_hold"],
                    "batteryPercentage": battery_percentage,
                    "health": {
                        "microcontrollerOk": True,
                        "imuOk": True,
                        "pressureSensorOk": True,
                        "escOk": True,
                    },
                },
            }
            try:
                await websocket.send(json.dumps(status_msg))
            except Exception:
                break
            await asyncio.sleep(0.5)

    telemetry_task = asyncio.create_task(send_telemetry())
    status_task = asyncio.create_task(send_status())

    try:
        await asyncio.sleep(5)
        firmware_msg = {"type": "firmwareVersion", "payload": FIRMWARE_VERSION}
        await websocket.send(json.dumps(firmware_msg))
        config_msg = {"type": "config", "payload": MOCK_CONFIG}
        await websocket.send(json.dumps(config_msg))

        last_direction_vector = None
        async for message in websocket:
            try:
                data = cast(dict[str, Any], json.loads(message))  # pyright: ignore[reportExplicitAny]
                msg_type = data.get("type")
                payload = data.get("payload")

                if msg_type == "directionVector":
                    if last_direction_vector != payload:
                        logger.info(f"DirectionVector: {payload}")
                        last_direction_vector = payload
                elif msg_type == "getConfig":
                    config_msg = {"type": "config", "payload": MOCK_CONFIG}
                    await websocket.send(json.dumps(config_msg))
                elif msg_type == "setConfig":
                    MOCK_CONFIG = payload  # pyright: ignore[reportConstantRedefinition]
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "id": None,
                            "toastType": "success",
                            "message": "ROV config set successfully",
                            "description": None,
                            "cancel": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))
                elif msg_type == "togglePitchStabilization":
                    SYSTEM_STATUS["pitch_stabilization"] = not SYSTEM_STATUS[
                        "pitch_stabilization"
                    ]
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Pitch stabilization set to {SYSTEM_STATUS['pitch_stabilization']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "toggleRollStabilization":
                    SYSTEM_STATUS["roll_stabilization"] = not SYSTEM_STATUS[
                        "roll_stabilization"
                    ]
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Roll stabilization set to {SYSTEM_STATUS['roll_stabilization']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "toggleDepthHold":
                    SYSTEM_STATUS["depth_hold"] = not SYSTEM_STATUS["depth_hold"]
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Depth hold set to {SYSTEM_STATUS['depth_hold']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "customAction":
                    logger.info(f"Custom action: {payload}")
                else:
                    logger.warning(f"Unhandled message type: {msg_type}")
                    logger.info(payload)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message")

    except Exception as e:
        logger.info(f"Client disconnected: {e}")
    finally:
        _ = telemetry_task.cancel()
        _ = status_task.cancel()


async def main() -> None:
    """Run the mock websocket server."""
    parser = argparse.ArgumentParser(description="Mock websocket server")
    _ = parser.add_argument(
        "--local",
        action="store_true",
        help="Use local IP 127.0.0.1 instead of 10.10.10.10",
    )
    args = parser.parse_args()
    host = "127.0.0.1" if cast(bool, args.local) else "10.10.10.10"

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    server = None
    try:
        server = await websockets.serve(_handle_client, host, PORT)
        logger.info(f"Mock websocket server running on {host}:{PORT}")
        await server.wait_closed()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Server stopped")
    finally:
        if server:
            server.close()
            await server.wait_closed()
