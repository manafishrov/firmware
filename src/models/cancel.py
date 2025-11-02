"""Cancel message models for the ROV firmware."""

from ..websocket.types import MessageType
from .base import CamelCaseModel
from .config import ThrusterTest


class CancelThrusterTest(CamelCaseModel):
    """WebSocket message for canceling thruster test."""

    type: MessageType = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest


class CancelRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for canceling regulator auto tuning."""

    type: MessageType = MessageType.CANCEL_REGULATOR_AUTO_TUNING
