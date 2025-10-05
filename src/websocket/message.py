from enum import Enum

from ..models.log import LogEntry
from ..models.toast import Toast
from ..models.config import RovConfig, ThrusterTest, FirmwareVersion
from ..models.rov_telemetry import RovTelemetry
from ..models.rov_status import RovStatus
from ..models.base import CamelCaseModel


class MessageType(str, Enum):
    TELEMETRY = "telemetry"
    STATUS_UPDATE = "statusUpdate"
    FIRMWARE_VERSION = "firmwareVersion"
    CONFIG = "config"
    SET_CONFIG = "setConfig"
    SHOW_TOAST = "showToast"
    LOG_MESSAGE = "logMessage"
    CANCEL_REGULATOR_AUTO_TUNING = "cancelRegulatorAutoTuning"
    CANCEL_THRUSTER_TEST = "cancelThrusterTest"


class Telemetry(CamelCaseModel):
    type: MessageType = MessageType.TELEMETRY
    payload: RovTelemetry


class StatusUpdate(CamelCaseModel):
    type: MessageType = MessageType.STATUS_UPDATE
    payload: RovStatus


class FirmwareVersion(CamelCaseModel):
    type: MessageType = MessageType.FIRMWARE_VERSION
    payload: FirmwareVersion


class ConfigMessage(CamelCaseModel):
    type: MessageType = MessageType.CONFIG
    payload: RovConfig


class ShowToast(CamelCaseModel):
    type: MessageType = MessageType.SHOW_TOAST
    payload: Toast


class LogMessage(CamelCaseModel):
    type: MessageType = MessageType.LOG_MESSAGE
    payload: LogEntry


class CancelRegulatorAutoTuning(CamelCaseModel):
    type: MessageType = MessageType.CANCEL_REGULATOR_AUTO_TUNING


class CancelThrusterTest(CamelCaseModel):
    type: MessageType = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest
