from enum import Enum
from typing import Union, Annotated

from pydantic import Field

from ..models.actions import DirectionVector, CustomAction
from ..models.log import LogEntry
from ..models.toast import Toast
from ..models.config import (
    RovConfig,
    ThrusterTest,
    FirmwareVersion,
    RegulatorSuggestions,
    MicrocontrollerFirmwareVariant,
)
from ..models.rov_telemetry import RovTelemetry
from ..models.rov_status import RovStatus
from ..models.base import CamelCaseModel


class MessageType(str, Enum):
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


class DirectionVector(CamelCaseModel):
    type: MessageType = MessageType.DIRECTION_VECTOR
    payload: DirectionVector


class GetConfig(CamelCaseModel):
    type: MessageType = MessageType.GET_CONFIG


class SetConfig(CamelCaseModel):
    type: MessageType = MessageType.SET_CONFIG
    payload: RovConfig


class Config(CamelCaseModel):
    type: MessageType = MessageType.CONFIG
    payload: RovConfig


class StartThrusterTest(CamelCaseModel):
    type: MessageType = MessageType.START_THRUSTER_TEST
    payload: ThrusterTest


class CancelThrusterTest(CamelCaseModel):
    type: MessageType = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest


class StartRegulatorAutoTuning(CamelCaseModel):
    type: MessageType = MessageType.START_REGULATOR_AUTO_TUNING


class CancelRegulatorAutoTuning(CamelCaseModel):
    type: MessageType = MessageType.CANCEL_REGULATOR_AUTO_TUNING


class RegulatorSuggestions(CamelCaseModel):
    type: MessageType = MessageType.REGULATOR_SUGGESTIONS
    payload: RegulatorSuggestions


class ShowToast(CamelCaseModel):
    type: MessageType = MessageType.SHOW_TOAST
    payload: Toast


class LogMessage(CamelCaseModel):
    type: MessageType = MessageType.LOG_MESSAGE
    payload: LogEntry


class StatusUpdate(CamelCaseModel):
    type: MessageType = MessageType.STATUS_UPDATE
    payload: RovStatus


class Telemetry(CamelCaseModel):
    type: MessageType = MessageType.TELEMETRY
    payload: RovTelemetry


class FirmwareVersion(CamelCaseModel):
    type: MessageType = MessageType.FIRMWARE_VERSION
    payload: FirmwareVersion


class CustomAction(CamelCaseModel):
    type: MessageType = MessageType.CUSTOM_ACTION
    payload: CustomAction


class TogglePitchStabilization(CamelCaseModel):
    type: MessageType = MessageType.TOGGLE_PITCH_STABILIZATION


class ToggleRollStabilization(CamelCaseModel):
    type: MessageType = MessageType.TOGGLE_ROLL_STABILIZATION


class ToggleDepthHold(CamelCaseModel):
    type: MessageType = MessageType.TOGGLE_DEPTH_HOLD


class FlashMicrocontrollerFirmware(CamelCaseModel):
    type: MessageType = MessageType.FLASH_MICROCONTROLLER_FIRMWARE
    payload: MicrocontrollerFirmwareVariant


WebsocketMessage = Annotated[
    Union[
        DirectionVector,
        GetConfig,
        SetConfig,
        Config,
        StartThrusterTest,
        CancelThrusterTest,
        StartRegulatorAutoTuning,
        CancelRegulatorAutoTuning,
        RegulatorSuggestions,
        ShowToast,
        LogMessage,
        StatusUpdate,
        Telemetry,
        FirmwareVersion,
        CustomAction,
        TogglePitchStabilization,
        ToggleRollStabilization,
        ToggleDepthHold,
        FlashMicrocontrollerFirmware,
    ],
    Field(discriminator="type"),
]
