"""WebSocket message models for the ROV firmware."""

from typing import Annotated, Any, Literal

from pydantic import Field

from ..extensions.wire import (
    CapabilityCatalog,
    CapabilityRequest,
    CapabilityResponse,
    CapabilitySamples,
)
from ..models.base import CamelCaseModel
from ..models.config import (
    McuBoard,
    PartialRovConfig,
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


class GetConfig(CamelCaseModel):
    """WebSocket message for getting config."""

    type: Literal[MessageType.GET_CONFIG] = MessageType.GET_CONFIG


class SetConfigPayload(CamelCaseModel):
    """Correlated partial configuration mutation."""

    mutation_id: str
    config: PartialRovConfig


class SetConfig(CamelCaseModel):
    """WebSocket message for setting config."""

    type: Literal[MessageType.SET_CONFIG] = MessageType.SET_CONFIG
    payload: SetConfigPayload


class ImportConfigPayload(CamelCaseModel):
    """Correlated raw configuration import."""

    mutation_id: str
    config: dict[str, Any]


class ImportConfig(CamelCaseModel):
    """WebSocket message for importing a raw, validation-free config snapshot."""

    type: Literal[MessageType.IMPORT_CONFIG] = MessageType.IMPORT_CONFIG
    payload: ImportConfigPayload


class ConfigPayload(CamelCaseModel):
    """Canonical configuration plus an optional mutation correlation id."""

    mutation_id: str | None = None
    config: RovConfig
    error: str | None = Field(default=None, exclude_if=lambda value: value is None)


class Config(CamelCaseModel):
    """WebSocket message for config response."""

    type: Literal[MessageType.CONFIG] = MessageType.CONFIG
    payload: ConfigPayload


class ConfirmConfig(CamelCaseModel):
    """Application acknowledgement of an applied canonical config."""

    type: Literal[MessageType.CONFIRM_CONFIG] = MessageType.CONFIRM_CONFIG
    payload: str


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


class FlashMcuFirmware(CamelCaseModel):
    """WebSocket message for flashing MCU firmware."""

    type: Literal[MessageType.FLASH_MCU_FIRMWARE] = MessageType.FLASH_MCU_FIRMWARE
    payload: McuBoard


class FlashEscFirmware(CamelCaseModel):
    """WebSocket message for flashing all ESCs."""

    type: Literal[MessageType.FLASH_ESC_FIRMWARE] = MessageType.FLASH_ESC_FIRMWARE


WebsocketMessage = Annotated[
    CapabilityRequest
    | CapabilityResponse
    | CapabilityCatalog
    | CapabilitySamples
    | GetConfig
    | SetConfig
    | ImportConfig
    | Config
    | ConfirmConfig
    | StartThrusterTest
    | CancelThrusterTest
    | StartRegulatorAutoTuning
    | CancelRegulatorAutoTuning
    | RegulatorSuggestions
    | ShowToast
    | LogMessage
    | FlashMcuFirmware
    | FlashEscFirmware,
    Field(discriminator="type"),
]
