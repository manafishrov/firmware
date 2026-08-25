"""WebSocket message types for the ROV firmware."""

from enum import StrEnum


class MessageType(StrEnum):
    """Enum for WebSocket message types."""

    DIRECTION_VECTOR = "directionVector"
    GET_CONFIG = "getConfig"
    SET_CONFIG = "setConfig"
    IMPORT_CONFIG = "importConfig"
    CONFIG = "config"
    CONFIRM_CONFIG = "confirmConfig"
    START_THRUSTER_TEST = "startThrusterTest"
    CANCEL_THRUSTER_TEST = "cancelThrusterTest"
    START_REGULATOR_AUTO_TUNING = "startRegulatorAutoTuning"
    CANCEL_REGULATOR_AUTO_TUNING = "cancelRegulatorAutoTuning"
    REGULATOR_SUGGESTIONS = "regulatorSuggestions"
    SHOW_TOAST = "showToast"
    LOG_MESSAGE = "logMessage"
    STATUS_UPDATE = "statusUpdate"
    TELEMETRY = "telemetry"
    CUSTOM_ACTION = "customAction"
    TOGGLE_AUTO_STABILIZATION = "toggleAutoStabilization"
    TOGGLE_DEPTH_HOLD = "toggleDepthHold"
    SET_AUTO_STABILIZATION = "setAutoStabilization"
    SET_DEPTH_HOLD = "setDepthHold"
    SET_DESIRED_DEPTH = "setDesiredDepth"
    FLASH_MCU_FIRMWARE = "flashMcuFirmware"
    FLASH_ESC_FIRMWARE = "flashEscFirmware"
