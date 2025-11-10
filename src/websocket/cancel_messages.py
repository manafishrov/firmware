"""Cancel message models for WebSocket."""

from typing import Literal

from ..models.base import CamelCaseModel
from ..models.config import ThrusterTest
from .types import MessageType


class CancelThrusterTest(CamelCaseModel):
    """WebSocket message for canceling thruster test."""

    type: Literal[MessageType.CANCEL_THRUSTER_TEST] = MessageType.CANCEL_THRUSTER_TEST
    payload: ThrusterTest


class CancelRegulatorAutoTuning(CamelCaseModel):
    """WebSocket message for canceling regulator auto tuning."""

    type: Literal[MessageType.CANCEL_REGULATOR_AUTO_TUNING] = (
        MessageType.CANCEL_REGULATOR_AUTO_TUNING
    )
