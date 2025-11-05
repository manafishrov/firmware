"""This script mocks the websocket server for testing websocket connections."""

import asyncio
import json
import logging
import math
import time
from typing import Any, cast

import websockets
from websockets import ServerConnection


IP_ADDRESS = "10.10.10.10"
PORT = 9000
FIRMWARE_VERSION = "1.0.0"
MOCK_CONFIG = {
    "fluidType": "saltwater",
    "thrusterPinSetup": {
        "identifiers": [5, 4, 3, 1, 2, 7, 6, 8],
        "spinDirections": [1, -1, 1, -1, 1, -1, 1, -1],
    },
    "thrusterAllocation": [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    ],
    "regulator": {
        "turnSpeed": 40,
        "pitch": {"kp": 1, "ki": 0.0, "kd": 0.0},
        "roll": {"kp": 5, "ki": 0.0, "kd": 0.0},
        "depth": {"kp": 8, "ki": 2.8, "kd": 0.0},
    },
    "directionCoefficients": {
        "horizontal": 0.0,
        "strafe": 0.0,
        "vertical": 0.0,
        "pitch": 0.0,
        "yaw": 0.0,
        "roll": 0.0,
    },
    "power": {
        "userMaxPower": 1.0,
        "regulatorMaxPower": 1.0,
        "batteryMinVoltage": 10.0,
        "batteryMaxVoltage": 16.8,
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
                    "thrusterRpms": thruster_rpms,
                    "workIndicatorPercentage": round(work_indicator_percentage, 2),
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
            depth = 10 + 5 * math.sin(current_time / 4)
            water_temperature = 20 + 5 * math.cos(current_time / 5)
            electronics_temperature = 25 + 3 * math.sin(current_time / 6)

            status_msg = {
                "type": "statusUpdate",
                "payload": {
                    "pitchStabilization": SYSTEM_STATUS["pitch_stabilization"],
                    "rollStabilization": SYSTEM_STATUS["roll_stabilization"],
                    "depthHold": SYSTEM_STATUS["depth_hold"],
                    "batteryPercentage": battery_percentage,
                    "depth": round(depth, 2),
                    "waterTemperature": round(water_temperature, 2),
                    "electronicsTemperature": round(electronics_temperature, 2),
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
                elif msg_type == "toggleDepthStabilization":
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
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message")

    except Exception as e:
        logger.info(f"Client disconnected: {e}")
    finally:
        _ = telemetry_task.cancel()
        _ = status_task.cancel()


async def main() -> None:
    """Run the mock websocket server."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        server = await websockets.serve(_handle_client, IP_ADDRESS, PORT)
        logger.info(f"Mock websocket server running on {IP_ADDRESS}:{PORT}")
        await server.wait_closed()
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
