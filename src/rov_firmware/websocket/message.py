"""WebSocket message models for the ROV firmware."""

from typing import Annotated, Literal

from pydantic import Field

from ..models.actions import (
    CustomAction as CustomActionPayload,
    DirectionVector as DirectionVectorPayload,
)
from ..models.base import CamelCaseModel
from ..models.config import (
    FirmwareVersion as FirmwareVersionPayload,
    MicrocontrollerFirmwareVariant,
    RegulatorSuggestions as RegulatorSuggestionsPayload,
    RovConfig,
    ThrusterTest,
)
from ..models.log import LogEntry
from ..models.rov_status import RovStatus
from ..models.rov_telemetry import RovTelemetry
from ..models.toast import Toast
from .cancel_messages import CancelRegulatorAutoTuning, CancelThrusterTest
from .types import MessageType


class DirectionVector(CamelCaseModel):
    """WebSocket message for direction vector."""

    type: Literal[MessageType.DIRECTION_VECTOR] = MessageType.DIRECTION_VECTOR
    payload: DirectionVectorPayload


class GetConfig(CamelCaseModel):
    """WebSocket message for getting config."""

    type: Literal[MessageType.GET_CONFIG] = MessageType.GET_CONFIG


class SetConfig(CamelCaseModel):
    """WebSocket message for setting config."""

    type: Literal[MessageType.SET_CONFIG] = MessageType.SET_CONFIG
    payload: RovConfig


class Config(CamelCaseModel):
    """WebSocket message for config response."""

    type: Literal[MessageType.CONFIG] = MessageType.CONFIG
    payload: RovConfig


class StartThrusterTest(CamelCaseModel):
    """WebSocket message for starting thruster test."""

    type: Literal[MessageType.START_THRUSTER_TEST] = MessageType.START_THRUSTER_TEST
    payload: ThrusterTest


class StartRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for starting regulator auto tuning."""

    type: Literal[MessageType.START_REGULATOR_AUTO_TUNING] = (
        MessageType.START_REGULATOR_AUTO_TUNING
    )


class RegulatorSuggestions(CamelCaseModel):
    """WebSocket message for regulator suggestions."""

    type: Literal[MessageType.REGULATOR_SUGGESTIONS] = MessageType.REGULATOR_SUGGESTIONS
    payload: RegulatorSuggestionsPayload


class ShowToast(CamelCaseModel):
    """WebSocket message for showing toast."""

    type: Literal[MessageType.SHOW_TOAST] = MessageType.SHOW_TOAST
    payload: Toast


class LogMessage(CamelCaseModel):
    """WebSocket message for log messages."""

    type: Literal[MessageType.LOG_MESSAGE] = MessageType.LOG_MESSAGE
    payload: LogEntry


class StatusUpdate(CamelCaseModel):
    """WebSocket message for status updates."""

    type: Literal[MessageType.STATUS_UPDATE] = MessageType.STATUS_UPDATE
    payload: RovStatus


class Telemetry(CamelCaseModel):
    """WebSocket message for telemetry."""

    type: Literal[MessageType.TELEMETRY] = MessageType.TELEMETRY
    payload: RovTelemetry


class FirmwareVersion(CamelCaseModel):
    """WebSocket message for firmware version."""

    type: Literal[MessageType.FIRMWARE_VERSION] = MessageType.FIRMWARE_VERSION
    payload: FirmwareVersionPayload


class CustomAction(CamelCaseModel):
    """WebSocket message for custom actions."""

    type: Literal[MessageType.CUSTOM_ACTION] = MessageType.CUSTOM_ACTION
    payload: CustomActionPayload


class ToggleAutoStabilization(CamelCaseModel):
    """WebSocket message for toggling auto stabilization."""

    type: Literal[MessageType.TOGGLE_AUTO_STABILIZATION] = (
        MessageType.TOGGLE_AUTO_STABILIZATION
    )


class ToggleDepthHold(CamelCaseModel):
    """WebSocket message for toggling depth hold."""

    type: Literal[MessageType.TOGGLE_DEPTH_HOLD] = MessageType.TOGGLE_DEPTH_HOLD


class FlashMicrocontrollerFirmware(CamelCaseModel):
    """WebSocket message for flashing microcontroller firmware."""

    type: Literal[MessageType.FLASH_MICROCONTROLLER_FIRMWARE] = (
        MessageType.FLASH_MICROCONTROLLER_FIRMWARE
    )
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
    | ToggleAutoStabilization
    | ToggleDepthHold
    | FlashMicrocontrollerFirmware,
    Field(discriminator="type"),
]
