from typing import Union
from enum import Enum
from ..models.config import RovConfig
from ..models.rov_telemetry import RovTelemetry
from ..models.rov_status import RovStatus
from ..models.base import CamelCaseModel


class MessageType(str, Enum):
    TELEMETRY = "telemetry"
    STATUS_UPDATE = "statusUpdate"
    FIRMWARE_VERSION = "firmwareVersion"
    CONFIG = "config"
    SET_CONFIG = "setConfig"


class Telemetry(CamelCaseModel):
    type: MessageType = MessageType.TELEMETRY
    payload: RovTelemetry


class StatusUpdate(CamelCaseModel):
    type: MessageType = MessageType.STATUS_UPDATE
    payload: RovStatus


class FirmwareVersion(CamelCaseModel):
    type: MessageType = MessageType.FIRMWARE_VERSION
    payload: str


class ConfigMessage(CamelCaseModel):
    type: MessageType = MessageType.CONFIG
    payload: RovConfig


Message = Union[Telemetry, StatusUpdate, FirmwareVersion, ConfigMessage]
