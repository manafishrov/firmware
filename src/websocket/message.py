"""WebSocket message models for the ROV firmware."""

from enum import Enum
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from ..models.actions import CustomAction as CustomActionPayload


if TYPE_CHECKING:
    from ..models.actions import DirectionVector as DirectionVectorPayload
    from ..models.config import (
        FirmwareVersion as FirmwareVersionPayload,
        RegulatorSuggestions as RegulatorSuggestionsPayload,
    )
    from ..models.toast import Toast

from ..models.base import CamelCaseModel
from ..models.config import (
    MicrocontrollerFirmwareVariant,
    RovConfig,
    ThrusterTest,
)
from ..models.log import LogEntry
from ..models.rov_status import RovStatus
from ..models.rov_telemetry import RovTelemetry


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


class DirectionVector(CamelCaseModel):
    """WebSocket message for direction vector."""

    type: MessageType = MessageType.DIRECTION_VECTOR
    payload: DirectionVectorPayload


class GetConfig(CamelCaseModel):
    """WebSocket message for getting config."""

    type: MessageType = MessageType.GET_CONFIG


class SetConfig(CamelCaseModel):
    """WebSocket message for setting config."""

    type: MessageType = MessageType.SET_CONFIG
    payload: RovConfig


class Config(CamelCaseModel):
    """WebSocket message for config response."""

    type: MessageType = MessageType.CONFIG
    payload: RovConfig


class StartThrusterTest(CamelCaseModel):
    """WebSocket message for starting thruster test."""

    type: MessageType = MessageType.START_THRUSTER_TEST
    payload: ThrusterTest


class CancelThrusterTest(CamelCaseModel):
    """WebSocket message for canceling thruster test."""

    type: MessageType = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest


class StartRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for starting regulator auto tuning."""

    type: MessageType = MessageType.START_REGULATOR_AUTO_TUNING


class CancelRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for canceling regulator auto tuning."""

    type: MessageType = MessageType.CANCEL_REGULATOR_AUTO_TUNING


class RegulatorSuggestions(CamelCaseModel):
    """WebSocket message for regulator suggestions."""

    type: MessageType = MessageType.REGULATOR_SUGGESTIONS
    payload: RegulatorSuggestionsPayload


class ShowToast(CamelCaseModel):
    """WebSocket message for showing toast."""

    type: MessageType = MessageType.SHOW_TOAST
    payload: Toast


class LogMessage(CamelCaseModel):
    """WebSocket message for log messages."""

    type: MessageType = MessageType.LOG_MESSAGE
    payload: LogEntry


class StatusUpdate(CamelCaseModel):
    """WebSocket message for status updates."""

    type: MessageType = MessageType.STATUS_UPDATE
    payload: RovStatus


class Telemetry(CamelCaseModel):
    """WebSocket message for telemetry."""

    type: MessageType = MessageType.TELEMETRY
    payload: RovTelemetry


class FirmwareVersion(CamelCaseModel):
    """WebSocket message for firmware version."""

    type: MessageType = MessageType.FIRMWARE_VERSION
    payload: FirmwareVersionPayload


class CustomAction(CamelCaseModel):
    """WebSocket message for custom actions."""

    type: MessageType = MessageType.CUSTOM_ACTION
    payload: CustomActionPayload


class TogglePitchStabilization(CamelCaseModel):
    """WebSocket message for toggling pitch stabilization."""

    type: MessageType = MessageType.TOGGLE_PITCH_STABILIZATION


class ToggleRollStabilization(CamelCaseModel):
    """WebSocket message for toggling roll stabilization."""

    type: MessageType = MessageType.TOGGLE_ROLL_STABILIZATION


class ToggleDepthHold(CamelCaseModel):
    """WebSocket message for toggling depth hold."""

    type: MessageType = MessageType.TOGGLE_DEPTH_HOLD


class FlashMicrocontrollerFirmware(CamelCaseModel):
    """WebSocket message for flashing microcontroller firmware."""

    type: MessageType = MessageType.FLASH_MICROCONTROLLER_FIRMWARE
    payload: MicrocontrollerFirmwareVariant


WebsocketMessage = Annotated[
    DirectionVector
    | GetConfig
    | SetConfig
    | Config
    | StartThrusterTest
    | CancelThrusterTest
    | StartRegulatorAutoTuning
    | CancelRegulatorAutoTuning
    | RegulatorSuggestions
    | ShowToast
    | LogMessage
    | StatusUpdate
    | Telemetry
    | FirmwareVersion
    | CustomAction
    | TogglePitchStabilization
    | ToggleRollStabilization
    | ToggleDepthHold
    | FlashMicrocontrollerFirmware,
    Field(discriminator="type"),
]
