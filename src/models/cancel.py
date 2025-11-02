"""Cancel message models for the ROV firmware."""

from typing import Literal

from ..websocket.types import MessageType
from .base import CamelCaseModel
from .config import ThrusterTest


class CancelThrusterTest(CamelCaseModel):
    """WebSocket message for canceling thruster test."""

    type: Literal[MessageType.CANCEL_THRUSTER_TEST] = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest


class CancelRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for canceling regulator auto tuning."""

    type: Literal[MessageType.CANCEL_REGULATOR_AUTO_TUNING] = (
        MessageType.CANCEL_REGULATOR_AUTO_TUNING
    )
