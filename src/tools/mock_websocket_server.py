"""This script mocks the websocket server for testing websocket connections."""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, cast

from pydantic import JsonValue
import websockets
from websockets import ServerConnection

from rov_firmware.custom_actions.api import dispatch
from rov_firmware.custom_actions.runtime import STATUS_PERIOD, CustomActionRuntime
from rov_firmware.models.config import CURRENT_FIRMWARE_VERSION, RovConfig
from rov_firmware.rov_state import RovState
from tools.mock_esc_firmware import MockEscFirmware


WEBSOCKET_PORT = 9000
MOCK_CONFIG: dict[str, Any] = {
    "firmwareVersion": CURRENT_FIRMWARE_VERSION,
    "rovName": "Manafish-m0ck",
    "mcuBoard": "pico",
    "thrusterProtocol": "dshot",
    "dshotSpeed": 300,
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
    "nullspaceVectors": [],
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
    "camera": {
        "width": 1024,
        "height": 768,
        "framerate": 30,
        "cropFov": False,
        "bitrate": 3538944,
        "keyframeInterval": 30,
        "profile": "baseline",
        "level": "4.2",
        "rotation": 0,
        "hflip": False,
        "vflip": False,
        "awb": "auto",
        "exposureValue": 0.0,
        "brightness": 0.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "sharpness": 1.0,
        "denoise": "off",
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
FLASH_TOAST_ID = "flash-mcu-firmware"
ESC_FLASH_TOAST_ID = "flash-esc-firmware"
THRUSTER_TEST_DURATION_SECONDS = 10
AUTO_TUNING_OSCILLATION_DURATION_SECONDS = 10
FLASH_DURATION_SECONDS = 3
PERCENT_COMPLETE = 100
MOCK_ESC_FIRMWARE = MockEscFirmware(flash_duration_seconds=FLASH_DURATION_SECONDS)
MCU_FLASH_TASK: asyncio.Task[None] | None = None
CAPABILITY_PERIOD_SECONDS = 1 / 60

type Control = Callable[[str, JsonValue], Awaitable[None]]


def _telemetry_readings(current_time: float) -> dict[str, Any]:
    """Simulate the readings the firmware samples at the capability rate."""
    depth = 10 + 5 * math.sin(current_time / 4)
    if SYSTEM_STATUS["depthHold"]:
        desired_depth = SYSTEM_STATUS["desiredDepth"]
    elif SYSTEM_STATUS["pendingDesiredDepth"] is not None:
        desired_depth = SYSTEM_STATUS["pendingDesiredDepth"]
    else:
        desired_depth = depth
    return {
        "pitch": round(20 * math.sin(current_time / 2), 2),
        "roll": round(15 * math.cos(current_time / 3), 2),
        "yaw": round(30 * math.sin(current_time / 2.5), 2),
        "depth": round(depth, 2),
        "desiredPitch": round(25 * math.sin(current_time / 2), 2),
        "desiredRoll": round(20 * math.cos(current_time / 3), 2),
        "desiredYaw": round(35 * math.sin(current_time / 2.5), 2),
        "desiredDepth": round(desired_depth, 2),
        "waterTemperature": round(20 + 5 * math.cos(current_time / 5), 2),
        "electronicsTemperature": round(25 + 3 * math.sin(current_time / 6), 2),
        "thrusterRpms": [
            int(1000 + 500 * math.sin(current_time + i)) for i in range(8)
        ],
        "thrusterSignalQualities": [
            round(100 - abs(2 * math.sin(current_time / 3 + i)), 2) for i in range(8)
        ],
        "workIndicatorPercentage": int(50 + 30 * math.sin(current_time / 10)),
    }


def _status_readings(current_time: float) -> dict[str, Any]:
    """Simulate the readings the firmware samples at the status rate."""
    esc_versions, esc_update = MOCK_ESC_FIRMWARE.status_payload()
    return {
        "autoStabilization": SYSTEM_STATUS["autoStabilization"],
        "depthHold": SYSTEM_STATUS["depthHold"],
        "batteryPercentage": int((math.sin(current_time / 5) + 1) * 50),
        "currentDraw": int(20 + 10 * math.sin(current_time / 4)),
        "piUndervoltage": False,
        "thrusterControlReady": True,
        "thrusterProtocolState": "ready",
        "thrusterProtocolError": None,
        "health": {
            "mcuHealthy": True,
            "imuHealthy": True,
            "pressureSensorHealthy": True,
        },
        "deviceInfo": {
            "mcuFirmwareVersion": "1.0.4-rc.1",
            "mcuFirmwareVersionStatus": "reported",
            "escFirmwareVersions": esc_versions,
            "escFirmwareVersionStatus": "reported",
        },
        "escFirmwareUpdate": esc_update,
    }


class MockCapabilities(CustomActionRuntime):
    """The firmware's capability runtime, fed by simulated vehicle readings.

    Catalog, samples, custom actions and CSV logs use the real implementation, so
    the mock speaks the same capability protocol as the firmware. Built-in `rov.*`
    actions go to the connected client's simulation instead of the Pico.
    """

    def __init__(self, directory: Path) -> None:
        """Keep custom actions, CSV logs and config in a throwaway directory."""
        config_path = RovConfig._config_path
        RovConfig._config_path = directory / "config.json"
        try:
            state = RovState()
        finally:
            RovConfig._config_path = config_path
        self.control: Control | None = None
        self._last_status = float("-inf")
        super().__init__(state, directory / "custom_actions")

    def refresh_builtins(self) -> None:
        """Publish simulated readings that changed, like the firmware does."""
        current_time = time.time()
        readings = _telemetry_readings(current_time)
        now = time.monotonic()
        if now - self._last_status >= STATUS_PERIOD:
            self._last_status = now
            readings.update(_status_readings(current_time))
        for key, value in readings.items():
            identifier = f"rov.{key}"
            previous = self.samples.get(identifier)
            if previous is None or previous.value != value:
                self.publish(identifier, value)

    async def invoke(
        self,
        identifier: str,
        phase: str = "press",
        value: JsonValue = None,
        *,
        once: bool = False,
    ) -> None:
        """Simulate built-in vehicle controls; run custom actions for real."""
        if not identifier.startswith("rov."):
            logging.getLogger(__name__).info(f"Custom action {identifier}: {phase}")
            await super().invoke(identifier, phase, value, once=once)
            return
        if identifier not in self.actions:
            msg = f"Action {identifier} is not available"
            raise ValueError(msg)
        if phase == "press" and self.control is not None:
            await self.control(identifier, value)


CAPABILITIES: MockCapabilities | None = None


def _capabilities() -> MockCapabilities:
    global CAPABILITIES  # noqa: PLW0603
    if CAPABILITIES is None:
        data_dir = os.environ.get("MANAFISH_DATA_DIR") or tempfile.mkdtemp(
            prefix="manafish-mock-"
        )
        CAPABILITIES = MockCapabilities(Path(data_dir))
    return CAPABILITIES


def _update_mock_config(payload: dict[str, Any], *, imported: bool = False) -> None:
    """Apply a partial config while preserving canonical mock-owned fields."""
    update = dict(payload)
    if imported:
        update.pop("firmwareVersion", None)

    camera = update.get("camera")
    current_camera = MOCK_CONFIG.get("camera")
    if isinstance(camera, dict) and isinstance(current_camera, dict):
        update["camera"] = {**current_camera, **camera}

    MOCK_CONFIG.update(update)


def _config_message(mutation_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"config": MOCK_CONFIG}
    if mutation_id is not None:
        payload["mutationId"] = mutation_id
    return {"type": "config", "payload": payload}


def _success_toast(message_key: str) -> dict[str, Any]:
    return {
        "type": "showToast",
        "payload": {
            "identifier": None,
            "variant": "success",
            "content": {
                "messageKey": message_key,
                "descriptionKey": None,
                "descriptionArgs": None,
            },
            "action": None,
        },
    }


async def _handle_client(websocket: ServerConnection) -> None:  # noqa: C901,PLR0912,PLR0915
    """Handle a websocket client connection."""
    global MCU_FLASH_TASK  # noqa: PLW0603

    logger = logging.getLogger(__name__)
    logger.info(
        f"Client connected: {cast(tuple[str, int] | None, websocket.remote_address)}"
    )

    capabilities = _capabilities()
    # Like the firmware, serve one operator at a time; a second client would
    # otherwise take over the simulated controls.
    if capabilities.control is not None:
        await websocket.close(code=1008, reason="Another operator is connected")
        return

    async def send_capabilities() -> None:
        """Stream catalog changes and samples like the firmware does."""
        while True:
            capabilities.refresh_builtins()
            if capabilities.catalog_changed:
                capabilities.catalog_changed = False
                await send_mock_message(
                    {"type": "capabilityCatalog", "payload": capabilities.catalog()}
                )
            samples = list(capabilities.events)
            capabilities.events.clear()
            if samples:
                await send_mock_message(
                    {
                        "type": "capabilitySamples",
                        "payload": {
                            "version": 1,
                            "samples": [
                                sample.model_dump(by_alias=True) for sample in samples
                            ],
                        },
                    }
                )
            await asyncio.sleep(CAPABILITY_PERIOD_SECONDS)

    async def respond_to_capability(payload: dict[str, Any]) -> None:
        """Answer a capability request through the firmware's dispatcher."""
        response: dict[str, Any] = {"version": 1, "requestId": payload["requestId"]}
        try:
            result = await dispatch(
                capabilities, payload["operation"], payload.get("params") or {}
            )
            response.update({"ok": True, "result": result})
        except Exception as error:
            logger.warning(f"Capability {payload.get('operation')}: {error}")
            response.update(
                {
                    "ok": False,
                    "error": {"code": "operation_failed", "message": str(error)},
                }
            )
        await send_mock_message({"type": "capabilityResponse", "payload": response})

    capability_task: asyncio.Task[None] | None = None
    capability_requests: set[asyncio.Task[None]] = set()
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

    async def run_flash_firmware(variant: str) -> None:
        """Simulate firmware flashing with progress toast updates."""
        try:
            start_time = time.time()
            last_percent = -1

            while True:
                elapsed = time.time() - start_time
                percent = min(
                    PERCENT_COMPLETE,
                    int((elapsed / FLASH_DURATION_SECONDS) * PERCENT_COMPLETE),
                )

                if percent != last_percent:
                    last_percent = percent
                    toast_msg = {
                        "type": "showToast",
                        "payload": {
                            "identifier": FLASH_TOAST_ID,
                            "variant": "loading",
                            "content": {
                                "messageKey": "toasts_flash_in_progress",
                                "messageArgs": {"percent": percent},
                            },
                            "action": None,
                        },
                    }
                    await websocket.send(json.dumps(toast_msg))

                if percent >= PERCENT_COMPLETE:
                    break
                await asyncio.sleep(0.05)

            toast_msg = {
                "type": "showToast",
                "payload": {
                    "identifier": FLASH_TOAST_ID,
                    "variant": "success",
                    "content": {
                        "messageKey": "toasts_flash_success",
                    },
                    "action": None,
                },
            }
            await websocket.send(json.dumps(toast_msg))
            logger.info(f"Mock flash complete: {variant}")
        except asyncio.CancelledError:
            logger.debug("Flash cancelled")
        except Exception:
            logger.exception("Error in mock flash")

    async def reject_concurrent_firmware_flash(
        identifier: str, message_key: str
    ) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "showToast",
                    "payload": {
                        "identifier": identifier,
                        "variant": "error",
                        "content": {"messageKey": message_key},
                        "action": None,
                    },
                }
            )
        )

    async def send_mock_message(message: dict[str, Any]) -> None:
        await websocket.send(json.dumps(message))

    async def send_log(message: str) -> None:
        await send_mock_message(
            {
                "type": "logMessage",
                "payload": {"origin": "firmware", "level": "info", "message": message},
            }
        )

    async def start_thruster_test(thruster_index: int) -> None:
        nonlocal thruster_test_task
        if thruster_test_task is not None and not thruster_test_task.done():
            _ = thruster_test_task.cancel()
        thruster_test_task = asyncio.create_task(run_thruster_test(thruster_index))

    async def cancel_thruster_test() -> None:
        SYSTEM_STATUS["thrusterTest"]["active"] = False
        if thruster_test_task is not None and not thruster_test_task.done():
            _ = thruster_test_task.cancel()
        await send_mock_message(
            {
                "type": "showToast",
                "payload": {
                    "identifier": THRUSTER_TEST_TOAST_ID,
                    "variant": "info",
                    "content": {"messageKey": "toasts_thruster_test_cancelled"},
                    "action": None,
                },
            }
        )

    async def start_auto_tuning() -> None:
        nonlocal auto_tuning_task
        if auto_tuning_task is not None and not auto_tuning_task.done():
            _ = auto_tuning_task.cancel()
        auto_tuning_task = asyncio.create_task(run_auto_tuning())

    async def cancel_auto_tuning() -> None:
        SYSTEM_STATUS["autoTuning"]["active"] = False
        if auto_tuning_task is not None and not auto_tuning_task.done():
            _ = auto_tuning_task.cancel()
        await send_mock_message(
            {
                "type": "showToast",
                "payload": {
                    "identifier": AUTO_TUNING_TOAST_ID,
                    "variant": "info",
                    "content": {"messageKey": "toasts_auto_tuning_cancelled"},
                    "action": None,
                },
            }
        )

    def set_depth_hold(enabled: bool) -> None:
        if enabled and not SYSTEM_STATUS["depthHold"]:
            pending = SYSTEM_STATUS["pendingDesiredDepth"]
            SYSTEM_STATUS["desiredDepth"] = (
                pending if pending is not None else 10 + 5 * math.sin(time.time() / 4)
            )
        if not enabled:
            SYSTEM_STATUS["pendingDesiredDepth"] = None
        SYSTEM_STATUS["depthHold"] = enabled

    last_direction: JsonValue = None

    async def control(identifier: str, value: JsonValue) -> None:  # noqa: C901
        """Simulate a built-in `rov.*` action in place of the Pico."""
        nonlocal last_direction
        if identifier == "rov.direction":
            if value != last_direction:
                logger.info(f"Direction: {value}")
                last_direction = value
        elif identifier == "rov.attitude.set":
            logger.info(f"Desired attitude: {value}")
        elif identifier in {
            "rov.autoStabilization.set",
            "rov.autoStabilization.toggle",
        }:
            SYSTEM_STATUS["autoStabilization"] = (
                bool(value)
                if identifier.endswith(".set")
                else not SYSTEM_STATUS["autoStabilization"]
            )
            await send_log(
                f"Auto stabilization set to {SYSTEM_STATUS['autoStabilization']}"
            )
        elif identifier in {"rov.depthHold.set", "rov.depthHold.toggle"}:
            set_depth_hold(
                bool(value)
                if identifier.endswith(".set")
                else not SYSTEM_STATUS["depthHold"]
            )
            await send_log(f"Depth hold set to {SYSTEM_STATUS['depthHold']}")
        elif identifier == "rov.desiredDepth.set":
            desired_depth = float(cast(float, value))
            if not math.isfinite(desired_depth):
                msg = "Desired depth must be finite"
                raise ValueError(msg)
            clamped = max(0.0, desired_depth)
            SYSTEM_STATUS["pendingDesiredDepth"] = clamped
            if SYSTEM_STATUS["depthHold"]:
                SYSTEM_STATUS["desiredDepth"] = clamped
            await send_log(f"Desired depth set to {SYSTEM_STATUS['desiredDepth']}")
        elif identifier == "rov.thrusterTest.start":
            await start_thruster_test(cast(int, value))
        elif identifier == "rov.thrusterTest.cancel":
            await cancel_thruster_test()
        elif identifier == "rov.regulatorAutoTuning.start":
            await start_auto_tuning()
        elif identifier == "rov.regulatorAutoTuning.cancel":
            await cancel_auto_tuning()

    try:
        await websocket.send(json.dumps(_config_message()))
        capabilities.control = control
        await capabilities.connected()
        capabilities.catalog_changed = True
        capability_task = asyncio.create_task(send_capabilities())

        pending_connection_mutation: str | None = None
        pending_connection_toast: dict[str, Any] | None = None
        async for message in websocket:
            try:
                data = cast(dict[str, Any], json.loads(message))
                msg_type = data.get("type")
                payload = data.get("payload")

                if msg_type == "capabilityRequest":
                    request = asyncio.create_task(
                        respond_to_capability(cast(dict[str, Any], payload))
                    )
                    capability_requests.add(request)
                    request.add_done_callback(capability_requests.discard)
                elif msg_type == "getConfig":
                    await websocket.send(json.dumps(_config_message()))
                elif msg_type == "setConfig":
                    previous_connection = (
                        MOCK_CONFIG.get("ipAddress"),
                        MOCK_CONFIG.get("websocketPort"),
                    )
                    mutation_id = None
                    if isinstance(payload, dict):
                        mutation_id = payload.get("mutationId")
                        config = payload.get("config")
                        if isinstance(config, dict):
                            _update_mock_config(cast(dict[str, Any], config))
                    await websocket.send(json.dumps(_config_message(mutation_id)))
                    toast_msg = _success_toast("toasts_rov_config_set_successfully")
                    current_connection = (
                        MOCK_CONFIG.get("ipAddress"),
                        MOCK_CONFIG.get("websocketPort"),
                    )
                    if current_connection != previous_connection and isinstance(
                        mutation_id, str
                    ):
                        pending_connection_mutation = mutation_id
                        pending_connection_toast = toast_msg
                    else:
                        await websocket.send(json.dumps(toast_msg))
                elif msg_type == "confirmConfig":
                    if payload == pending_connection_mutation:
                        if pending_connection_toast is not None:
                            await websocket.send(json.dumps(pending_connection_toast))
                        await websocket.close(
                            reason="Mock ROV connection settings changed"
                        )
                        return
                elif msg_type == "importConfig":
                    previous_connection = (
                        MOCK_CONFIG.get("ipAddress"),
                        MOCK_CONFIG.get("websocketPort"),
                    )
                    mutation_id = None
                    if isinstance(payload, dict):
                        mutation_id = payload.get("mutationId")
                        config = payload.get("config")
                        if isinstance(config, dict):
                            _update_mock_config(
                                cast(dict[str, Any], config), imported=True
                            )
                    await websocket.send(json.dumps(_config_message(mutation_id)))
                    toast_msg = _success_toast("toasts_rov_config_imported")
                    current_connection = (
                        MOCK_CONFIG.get("ipAddress"),
                        MOCK_CONFIG.get("websocketPort"),
                    )
                    if current_connection != previous_connection and isinstance(
                        mutation_id, str
                    ):
                        pending_connection_mutation = mutation_id
                        pending_connection_toast = toast_msg
                    else:
                        await websocket.send(json.dumps(toast_msg))
                elif msg_type == "flashMcuFirmware":
                    if (
                        MCU_FLASH_TASK is not None and not MCU_FLASH_TASK.done()
                    ) or MOCK_ESC_FIRMWARE.active:
                        await reject_concurrent_firmware_flash(
                            FLASH_TOAST_ID, "toasts_flash_failed"
                        )
                    else:
                        MCU_FLASH_TASK = asyncio.create_task(
                            run_flash_firmware(cast(str, payload))
                        )
                elif msg_type == "flashEscFirmware":
                    mcu_flash_active = (
                        MCU_FLASH_TASK is not None and not MCU_FLASH_TASK.done()
                    )
                    started = False
                    if not mcu_flash_active:
                        started = await MOCK_ESC_FIRMWARE.start(send_mock_message)
                    if not started:
                        await reject_concurrent_firmware_flash(
                            ESC_FLASH_TOAST_ID, "toasts_esc_flash_failed"
                        )
                elif msg_type == "startThrusterTest":
                    await start_thruster_test(cast(int, payload))
                elif msg_type == "cancelThrusterTest":
                    await cancel_thruster_test()
                elif msg_type == "startRegulatorAutoTuning":
                    await start_auto_tuning()
                elif msg_type == "cancelRegulatorAutoTuning":
                    await cancel_auto_tuning()
                else:
                    logger.warning(f"Unhandled message type: {msg_type}")
                    logger.info(payload)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message")

    except Exception as e:
        logger.info(f"Client disconnected: {e}")
    finally:
        capabilities.control = None
        tasks = [
            task
            for task in (
                capability_task,
                thruster_test_task,
                auto_tuning_task,
                *capability_requests,
            )
            if task is not None
        ]
        for task in tasks:
            _ = task.cancel()
        _ = await asyncio.gather(*tasks, return_exceptions=True)
        await capabilities.disconnected()


async def main() -> None:
    """Run the mock websocket server."""
    parser = argparse.ArgumentParser(description="Mock websocket server")
    _ = parser.add_argument(
        "--local",
        action="store_true",
        help="Use local IP 127.0.0.1 instead of 10.10.10.10",
    )
    _ = parser.add_argument(
        "--host",
        help="Listen on this address, such as this computer's LAN address for a phone or simulator",
    )
    args = parser.parse_args()
    host = cast(str | None, args.host) or (
        "127.0.0.1" if cast(bool, args.local) else "10.10.10.10"
    )
    MOCK_CONFIG["ipAddress"] = host

    logger = logging.getLogger(__name__)

    server = None
    try:
        server = await websockets.serve(_handle_client, host, WEBSOCKET_PORT)
        logger.info(f"Mock websocket server running on {host}:{WEBSOCKET_PORT}")
        await server.wait_closed()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Server stopped")
    finally:
        await MOCK_ESC_FIRMWARE.shutdown()
        if MCU_FLASH_TASK is not None and not MCU_FLASH_TASK.done():
            _ = MCU_FLASH_TASK.cancel()
            _ = await asyncio.gather(MCU_FLASH_TASK, return_exceptions=True)
        if server:
            server.close()
            await server.wait_closed()
