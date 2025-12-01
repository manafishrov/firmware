"""WebSocket message types for the ROV firmware."""

from enum import Enum


class MessageType(str, Enum):
    """Enum for WebSocket message types."""

    DIRECTION_VECTOR = "directionVector"
    GET_CONFIG = "getConfig"
    SET_CONFIG = "setConfig"
    CONFIG = "config"
    START_THRUSTER_TEST = "startThrusterTest"
    CANCEL_THRUSTER_TEST = "cancelThrusterTest"
    START_REGULATOR_AUTO_TUNING = "startRegulatorAutoTuning"
    CANCEL_REGULATOR_AUTO_TUNING = "cancelRegulatorAutoTuning"
    REGULATOR_SUGGESTIONS = "regulatorSuggestions"
    SHOW_TOAST = "showToast"
    LOG_MESSAGE = "logMessage"
    STATUS_UPDATE = "statusUpdate"
    TELEMETRY = "telemetry"
    FIRMWARE_VERSION = "firmwareVersion"
    CUSTOM_ACTION = "customAction"
    TOGGLE_PITCH_STABILIZATION = "togglePitchStabilization"
    TOGGLE_ROLL_STABILIZATION = "toggleRollStabilization"
    TOGGLE_DEPTH_HOLD = "toggleDepthHold"
    FLASH_MICROCONTROLLER_FIRMWARE = "flashMicrocontrollerFirmware"
