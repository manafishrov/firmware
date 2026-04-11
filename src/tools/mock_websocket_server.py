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


WEBSOCKET_PORT = 9000
MOCK_CONFIG: dict[str, Any] = {
    "firmwareVersion": "1.0.0",
    "rovName": "Manafish-m0ck",
    "microcontrollerFirmwareVariant": "dshot",
    "fluidType": "saltwater",
    "smoothingFactor": 0.0,
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
        "pitch": {"kp": 2, "ki": 0, "kd": 0.1, "rate": 5.0},
        "roll": {"kp": 1, "ki": 0, "kd": 0.1, "rate": 5.0},
        "yaw": {"kp": 3, "ki": 0, "kd": 0, "rate": 5.0},
        "depth": {"kp": 0.5, "ki": 0, "kd": 0.1, "rate": 5.0},
        "fpvMode": False,
    },
    "directionCoefficients": {
        "surge": 1.0,
        "sway": 1.0,
        "heave": 1.0,
    },
    "power": {
        "thrustersLimit": 30,
        "actionsLimit": 50,
        "regulatorLimit": 30,
        "minBatteryVoltage": 14.0,
        "maxBatteryVoltage": 21.5,
    },
    "ipAddress": "10.10.10.10",
    "websocketPort": 9000,
}

SYSTEM_STATUS: dict[str, Any] = {
    "autoStabilization": False,
    "depthHold": False,
    "desiredDepth": 12.0,
    "pendingDesiredDepth": None,
    "thrusterTest": {
        "active": False,
        "thrusterIndex": None,
        "startTime": None,
    },
    "autoTuning": {
        "active": False,
        "phase": None,
        "step": None,
        "startTime": None,
    },
}

THRUSTER_TEST_TOAST_ID = "thruster-test"
AUTO_TUNING_TOAST_ID = "regulator-auto-tuning"
THRUSTER_TEST_DURATION_SECONDS = 10
AUTO_TUNING_OSCILLATION_DURATION_SECONDS = 10


async def _handle_client(websocket: ServerConnection) -> None:  # noqa: C901,PLR0912,PLR0915
    """Handle a websocket client connection."""
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
            yaw = 30 * math.sin(current_time / 2.5)
            desired_pitch = 25 * math.sin(current_time / 2)
            desired_roll = 20 * math.cos(current_time / 3)
            desired_yaw = 35 * math.sin(current_time / 2.5)
            depth = 10 + 5 * math.sin(current_time / 4)
            if cast(bool, SYSTEM_STATUS["depthHold"]):
                desired_depth = cast(float, SYSTEM_STATUS["desiredDepth"])
            elif SYSTEM_STATUS["pendingDesiredDepth"] is not None:
                desired_depth = cast(float, SYSTEM_STATUS["pendingDesiredDepth"])
            else:
                desired_depth = depth
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
                    "yaw": round(yaw, 2),
                    "depth": round(depth, 2),
                    "desiredPitch": round(desired_pitch, 2),
                    "desiredRoll": round(desired_roll, 2),
                    "desiredYaw": round(desired_yaw, 2),
                    "desiredDepth": round(desired_depth, 2),
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
                    "autoStabilization": SYSTEM_STATUS["autoStabilization"],
                    "depthHold": SYSTEM_STATUS["depthHold"],
                    "batteryPercentage": battery_percentage,
                    "health": {
                        "microcontrollerHealthy": True,
                        "imuHealthy": True,
                        "pressureSensorHealthy": True,
                    },
                },
            }
            try:
                await websocket.send(json.dumps(status_msg))
            except Exception:
                break
            await asyncio.sleep(0.5)

    telemetry_task: asyncio.Task[None] = asyncio.create_task(send_telemetry())
    status_task: asyncio.Task[None] = asyncio.create_task(send_status())
    thruster_test_task: asyncio.Task[None] | None = None
    auto_tuning_task: asyncio.Task[None] | None = None

    async def run_thruster_test(thruster_index: int) -> None:
        """Simulate thruster test with progress toast updates."""
        try:
            SYSTEM_STATUS["thrusterTest"]["active"] = True
            SYSTEM_STATUS["thrusterTest"]["thrusterIndex"] = thruster_index
            SYSTEM_STATUS["thrusterTest"]["startTime"] = time.time()

            start_time = time.time()
            last_remaining = THRUSTER_TEST_DURATION_SECONDS

            toast_msg = {
                "type": "showToast",
                "payload": {
                    "identifier": THRUSTER_TEST_TOAST_ID,
                    "variant": "loading",
                    "content": {
                        "messageKey": "toasts_thruster_test_title",
                        "messageArgs": {"thruster": thruster_index},
                        "descriptionKey": "toasts_seconds_remaining",
                        "descriptionArgs": {"seconds": last_remaining},
                    },
                    "action": {
                        "labelKey": "common_cancel",
                        "messageType": "cancelThrusterTest",
                        "payload": thruster_index,
                    },
                },
            }
            await websocket.send(json.dumps(toast_msg))

            while SYSTEM_STATUS["thrusterTest"]["active"]:
                elapsed = time.time() - start_time
                remaining = int(THRUSTER_TEST_DURATION_SECONDS - elapsed)

                if elapsed >= THRUSTER_TEST_DURATION_SECONDS:
                    SYSTEM_STATUS["thrusterTest"]["active"] = False
                    SYSTEM_STATUS["thrusterTest"]["thrusterIndex"] = None
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": THRUSTER_TEST_TOAST_ID,
                            "variant": "success",
                            "content": {
                                "messageKey": "toasts_thruster_test_completed",
                                "descriptionKey": None,
                                "descriptionArgs": None,
                            },
                            "action": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))
                    break

                if remaining != last_remaining:
                    last_remaining = remaining
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": THRUSTER_TEST_TOAST_ID,
                            "variant": "loading",
                            "content": {
                                "messageKey": "toasts_thruster_test_title",
                                "messageArgs": {"thruster": thruster_index},
                                "descriptionKey": "toasts_seconds_remaining",
                                "descriptionArgs": {"seconds": remaining},
                            },
                            "action": {
                                "labelKey": "common_cancel",
                                "messageType": "cancelThrusterTest",
                                "payload": thruster_index,
                            },
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("Thruster test cancelled")
        except Exception:
            logger.exception("Error in thruster test")
        finally:
            SYSTEM_STATUS["thrusterTest"]["active"] = False
            SYSTEM_STATUS["thrusterTest"]["thrusterIndex"] = None

    async def run_auto_tuning() -> None:
        """Simulate regulator auto tuning with progress toast updates."""
        try:
            SYSTEM_STATUS["autoTuning"]["active"] = True
            SYSTEM_STATUS["autoTuning"]["startTime"] = time.time()

            toast_msg = {
                "type": "showToast",
                "payload": {
                    "identifier": AUTO_TUNING_TOAST_ID,
                    "variant": "loading",
                    "content": {
                        "messageKey": "toasts_auto_tuning_starting",
                        "descriptionKey": "toasts_auto_tuning_finding_zero",
                    },
                    "action": {
                        "labelKey": "common_cancel",
                        "messageType": "cancelRegulatorAutoTuning",
                    },
                },
            }
            await websocket.send(json.dumps(toast_msg))

            for phase in ("pitch", "roll", "depth"):
                if not SYSTEM_STATUS["autoTuning"]["active"]:
                    break
                await _run_tuning_phase(phase)

            if SYSTEM_STATUS["autoTuning"]["active"]:
                toast_msg = {
                    "type": "showToast",
                    "payload": {
                        "identifier": AUTO_TUNING_TOAST_ID,
                        "variant": "success",
                        "content": {
                            "messageKey": "toasts_auto_tuning_completed",
                            "descriptionKey": None,
                            "descriptionArgs": None,
                        },
                        "action": None,
                    },
                }
                await websocket.send(json.dumps(toast_msg))

        except asyncio.CancelledError:
            logger.debug("Auto tuning cancelled")
        except Exception:
            logger.exception("Error in auto tuning")
        finally:
            SYSTEM_STATUS["autoTuning"]["active"] = False
            SYSTEM_STATUS["autoTuning"]["phase"] = None
            SYSTEM_STATUS["autoTuning"]["step"] = None

    async def _run_tuning_phase(phase: str) -> None:
        SYSTEM_STATUS["autoTuning"]["phase"] = phase
        SYSTEM_STATUS["autoTuning"]["step"] = "find_zero"

        toast_msg = {
            "type": "showToast",
            "payload": {
                "identifier": AUTO_TUNING_TOAST_ID,
                "variant": "loading",
                "content": {
                    "messageKey": "toasts_auto_tuning_tuning_phase",
                    "messageArgs": {"phase": phase},
                    "descriptionKey": "toasts_auto_tuning_finding_zero",
                },
                "action": {
                    "labelKey": "common_cancel",
                    "messageType": "cancelRegulatorAutoTuning",
                },
            },
        }
        await websocket.send(json.dumps(toast_msg))
        await asyncio.sleep(2)

        if not SYSTEM_STATUS["autoTuning"]["active"]:
            return

        SYSTEM_STATUS["autoTuning"]["step"] = "find_amplitude"
        toast_msg = {
            "type": "showToast",
            "payload": {
                "identifier": AUTO_TUNING_TOAST_ID,
                "variant": "loading",
                "content": {
                    "messageKey": "toasts_auto_tuning_tuning_phase",
                    "messageArgs": {"phase": phase},
                    "descriptionKey": "toasts_auto_tuning_finding_oscillation",
                },
                "action": {
                    "labelKey": "common_cancel",
                    "messageType": "cancelRegulatorAutoTuning",
                },
            },
        }
        await websocket.send(json.dumps(toast_msg))
        await asyncio.sleep(2)

        if not SYSTEM_STATUS["autoTuning"]["active"]:
            return

        SYSTEM_STATUS["autoTuning"]["step"] = "oscillate"
        oscillation_start = time.time()
        last_elapsed = -1

        while SYSTEM_STATUS["autoTuning"]["active"]:
            elapsed = time.time() - oscillation_start
            if elapsed >= AUTO_TUNING_OSCILLATION_DURATION_SECONDS:
                break

            elapsed_int = int(elapsed)
            if elapsed_int != last_elapsed:
                last_elapsed = elapsed_int
                toast_msg = {
                    "type": "showToast",
                    "payload": {
                        "identifier": AUTO_TUNING_TOAST_ID,
                        "variant": "loading",
                        "content": {
                            "messageKey": "toasts_auto_tuning_tuning_phase",
                            "messageArgs": {"phase": phase},
                            "descriptionKey": "toasts_auto_tuning_oscillating",
                            "descriptionArgs": {"seconds": elapsed_int},
                        },
                        "action": {
                            "labelKey": "common_cancel",
                            "messageType": "cancelRegulatorAutoTuning",
                        },
                    },
                }
                await websocket.send(json.dumps(toast_msg))

            await asyncio.sleep(0.1)

    try:
        await asyncio.sleep(5)
        config_msg = {"type": "config", "payload": MOCK_CONFIG}
        await websocket.send(json.dumps(config_msg))

        last_direction_vector = None
        async for message in websocket:
            try:
                data = cast(dict[str, Any], json.loads(message))
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
                    if isinstance(payload, dict):
                        MOCK_CONFIG.update(cast(dict[str, Any], payload))
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": None,
                            "variant": "success",
                            "content": {
                                "messageKey": "toasts_rov_config_set_successfully",
                                "descriptionKey": None,
                                "descriptionArgs": None,
                            },
                            "action": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))
                elif msg_type == "toggleAutoStabilization":
                    SYSTEM_STATUS["autoStabilization"] = not SYSTEM_STATUS[
                        "autoStabilization"
                    ]
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Auto stabilization set to {SYSTEM_STATUS['autoStabilization']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "toggleDepthHold":
                    SYSTEM_STATUS["depthHold"] = not SYSTEM_STATUS["depthHold"]
                    if SYSTEM_STATUS["depthHold"]:
                        pending = SYSTEM_STATUS["pendingDesiredDepth"]
                        if pending is not None:
                            SYSTEM_STATUS["desiredDepth"] = pending
                        else:
                            current_time = time.time()
                            SYSTEM_STATUS["desiredDepth"] = 10 + 5 * math.sin(
                                current_time / 4
                            )
                    else:
                        SYSTEM_STATUS["pendingDesiredDepth"] = None
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Depth hold set to {SYSTEM_STATUS['depthHold']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "setDesiredDepth":
                    desired_depth = cast(float, payload)
                    if not math.isfinite(desired_depth):
                        logger.warning(f"Invalid desired depth payload: {payload}")
                        continue
                    clamped = max(0.0, desired_depth)
                    SYSTEM_STATUS["pendingDesiredDepth"] = clamped
                    if SYSTEM_STATUS["depthHold"]:
                        SYSTEM_STATUS["desiredDepth"] = clamped
                    log_msg = {
                        "type": "logMessage",
                        "payload": {
                            "origin": "firmware",
                            "level": "info",
                            "message": f"Desired depth set to {SYSTEM_STATUS['desiredDepth']}",
                        },
                    }
                    await websocket.send(json.dumps(log_msg))
                elif msg_type == "customAction":
                    logger.info(f"Custom action: {payload}")
                elif msg_type == "startThrusterTest":
                    if thruster_test_task is not None and not thruster_test_task.done():
                        _ = thruster_test_task.cancel()
                    thruster_test_task = asyncio.create_task(
                        run_thruster_test(cast(int, payload))
                    )
                elif msg_type == "cancelThrusterTest":
                    SYSTEM_STATUS["thrusterTest"]["active"] = False
                    if thruster_test_task is not None and not thruster_test_task.done():
                        _ = thruster_test_task.cancel()
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": THRUSTER_TEST_TOAST_ID,
                            "variant": "info",
                            "content": {
                                "messageKey": "toasts_thruster_test_cancelled",
                            },
                            "action": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))
                elif msg_type == "startRegulatorAutoTuning":
                    if auto_tuning_task is not None and not auto_tuning_task.done():
                        _ = auto_tuning_task.cancel()
                    auto_tuning_task = asyncio.create_task(run_auto_tuning())
                elif msg_type == "cancelRegulatorAutoTuning":
                    SYSTEM_STATUS["autoTuning"]["active"] = False
                    if auto_tuning_task is not None and not auto_tuning_task.done():
                        _ = auto_tuning_task.cancel()
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": AUTO_TUNING_TOAST_ID,
                            "variant": "info",
                            "content": {
                                "messageKey": "toasts_auto_tuning_cancelled",
                            },
                            "action": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))
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
        if thruster_test_task is not None:
            _ = thruster_test_task.cancel()
        if auto_tuning_task is not None:
            _ = auto_tuning_task.cancel()


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

    logger = logging.getLogger(__name__)

    server = None
    try:
        server = await websockets.serve(_handle_client, host, WEBSOCKET_PORT)
        logger.info(f"Mock websocket server running on {host}:{WEBSOCKET_PORT}")
        await server.wait_closed()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Server stopped")
    finally:
        if server:
            server.close()
            await server.wait_closed()
