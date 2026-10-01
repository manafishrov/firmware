"""Expose existing vehicle capabilities through the custom action contract."""

from functools import cache
from typing import Any, cast

from ..models.actions import DirectionVector
from ..models.config import ThrusterTest
from ..motor_safety import motor_firmware_operation_blocker
from ..rov_state import RovState
from ..websocket.receive.actions import (
    handle_cancel_thruster_test,
    handle_direction_vector,
    handle_start_thruster_test,
)
from ..websocket.receive.regulator import (
    handle_cancel_regulator_auto_tuning,
    handle_set_desired_depth,
    handle_start_regulator_auto_tuning,
)
from ..websocket.receive.state import (
    handle_set_auto_stabilization,
    handle_set_depth_hold,
    handle_toggle_auto_stabilization,
    handle_toggle_depth_hold,
)
from ..websocket.send.status import build_status_update
from ..websocket.send.telemetry import build_telemetry
from .models import Action, Reading
from .values import normalize_value


QUATERNION_COMPONENTS = 4

READING_DEFINITIONS = {
    "pitch": ("Pitch", "number", "°"),
    "roll": ("Roll", "number", "°"),
    "yaw": ("Heading", "number", "°"),
    "depth": ("Depth", "number", "m"),
    "desiredPitch": ("Target pitch", "number", "°"),
    "desiredRoll": ("Target roll", "number", "°"),
    "desiredYaw": ("Target heading", "number", "°"),
    "desiredDepth": ("Target depth", "number", "m"),
    "waterTemperature": ("Water temperature", "number", "°C"),
    "electronicsTemperature": ("Electronics temperature", "number", "°C"),
    "thrusterRpms": ("Thruster speeds", "numberArray", "rpm"),
    "thrusterSignalQualities": ("Thruster signal quality", "json", None),
    "workIndicatorPercentage": ("Thruster load", "number", "%"),
    "autoStabilization": ("Stabilization", "boolean", None),
    "depthHold": ("Depth hold", "boolean", None),
    "batteryPercentage": ("Battery", "number", "%"),
    "currentDraw": ("Current draw", "number", "A"),
    "piUndervoltage": ("Pi undervoltage", "boolean", None),
    "thrusterControlReady": ("Thrusters ready", "boolean", None),
    "thrusterProtocolState": ("Thruster connection", "string", None),
    "thrusterProtocolError": ("Thruster error", "string", None),
    "health": ("System health", "json", None),
    "deviceInfo": ("Device information", "json", None),
    "escFirmwareUpdate": ("ESC firmware update", "json", None),
}

ACTION_DEFINITIONS = [
    ("direction", "Vehicle movement", "numberArray"),
    ("autoStabilization.set", "Set stabilization", "boolean"),
    ("autoStabilization.toggle", "Toggle stabilization", "none"),
    ("depthHold.set", "Set depth hold", "boolean"),
    ("depthHold.toggle", "Toggle depth hold", "none"),
    ("desiredDepth.set", "Set desired depth", "number"),
    ("attitude.set", "Set desired attitude", "numberArray"),
    ("thrusterTest.start", "Start thruster test", "number"),
    ("thrusterTest.cancel", "Cancel thruster test", "number"),
    ("regulatorAutoTuning.start", "Start regulator tuning", "none"),
    ("regulatorAutoTuning.cancel", "Cancel regulator tuning", "none"),
]


def values(state: RovState, *, include_status: bool = True) -> dict[str, Any]:
    """Project current internal state into the single public reading namespace."""
    combined = build_telemetry(state).payload.model_dump(mode="json", by_alias=True)
    if include_status:
        combined.update(
            build_status_update(state).payload.model_dump(mode="json", by_alias=True)
        )
    return {f"rov.{key}": value for key, value in combined.items()}


def readings() -> list[Reading]:
    """Describe built-ins without making types depend on current availability."""
    return [
        Reading.model_validate(
            {"id": f"rov.{key}", "name": name, "valueType": kind, "unit": unit}
        )
        for key, (name, kind, unit) in READING_DEFINITIONS.items()
    ]


@cache
def actions() -> list[Action]:
    """List built-in controls alongside installed custom action actions."""
    return [
        Action.model_validate(
            {"id": f"rov.{identifier}", "name": name, "inputType": kind}
        )
        for identifier, name, kind in ACTION_DEFINITIONS
    ]


async def invoke(state: RovState, identifier: str, value: object) -> None:
    """Dispatch validated controls through existing motor safety handlers."""
    definitions = {action.id: action for action in actions()}
    action = definitions[identifier]
    if action.input_type != "none":
        value = normalize_value(value, action.input_type)
    controls = {
        "rov.autoStabilization.set": handle_set_auto_stabilization,
        "rov.depthHold.set": handle_set_depth_hold,
        "rov.desiredDepth.set": handle_set_desired_depth,
    }
    toggles = {
        "rov.autoStabilization.toggle": handle_toggle_auto_stabilization,
        "rov.depthHold.toggle": handle_toggle_depth_hold,
        "rov.regulatorAutoTuning.start": handle_start_regulator_auto_tuning,
        "rov.regulatorAutoTuning.cancel": handle_cancel_regulator_auto_tuning,
    }
    if identifier in controls:
        blocker = motor_firmware_operation_blocker(state)
        if blocker and (identifier == "rov.desiredDepth.set" or value is True):
            raise ValueError(blocker)
        if identifier == "rov.desiredDepth.set":
            await handle_set_desired_depth(state, cast(float, value))
        elif identifier == "rov.autoStabilization.set":
            await handle_set_auto_stabilization(state, cast(bool, value))
        else:
            await handle_set_depth_hold(state, cast(bool, value))
    elif identifier in toggles:
        await toggles[identifier](state)
    else:
        await _invoke_special(state, identifier, value)


async def _invoke_special(state: RovState, identifier: str, value: object) -> None:
    if identifier == "rov.direction":
        await handle_direction_vector(state, DirectionVector.model_validate(value))
    elif identifier == "rov.attitude.set":
        quaternion = cast(list[float], value)
        if len(quaternion) != QUATERNION_COMPONENTS:
            msg = "Attitude requires four quaternion components XYZW"
            raise ValueError(msg)
        await state.set_desired_attitude(
            cast(tuple[float, float, float, float], tuple(quaternion))
        )
    elif identifier == "rov.thrusterTest.start":
        await handle_start_thruster_test(state, ThrusterTest(cast(int, value)))
    elif identifier == "rov.thrusterTest.cancel":
        await handle_cancel_thruster_test(state, ThrusterTest(cast(int, value)))
