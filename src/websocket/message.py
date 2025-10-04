from pydantic import BaseModel
from typing import Union
from ..rov_config import ROVConfig
from ..base_model import CamelCaseModel
from enum import Enum


class MessageType(str, Enum):
    TELEMETRY = "telemetry"
    STATUS_UPDATE = "statusUpdate"
    FIRMWARE_VERSION = "firmwareVersion"
    CONFIG = "config"
    SET_CONFIG = "setConfig"


class TelemetryPayload(CamelCaseModel):
    pitch: float
    roll: float
    desired_pitch: float
    desired_roll: float
    depth: float
    temperature: float
    thruster_erpms: tuple[int, int, int, int, int, int, int, int]


class Telemetry(CamelCaseModel):
    type: MessageType = MessageType.TELEMETRY
    payload: TelemetryPayload


class StatusUpdatePayload(CamelCaseModel):
    pitch_stabilization: bool
    roll_stabilization: bool
    depth_stabilization: bool
    battery_percentage: int


class StatusUpdate(CamelCaseModel):
    type: MessageType = MessageType.STATUS_UPDATE
    payload: StatusUpdatePayload


class FirmwareVersion(CamelCaseModel):
    type: MessageType = MessageType.FIRMWARE_VERSION
    payload: str


class ConfigMessage(CamelCaseModel):
    type: MessageType = MessageType.CONFIG
    payload: ROVConfig


Message = Union[Telemetry, StatusUpdate, FirmwareVersion, ConfigMessage]
