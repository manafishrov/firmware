"""Regulator data models for the ROV firmware."""

from pydantic import BaseModel


class RegulatorData(BaseModel):
    """Model for regulator data."""

    pitch: float = 0.0
    roll: float = 0.0
    yaw: float = 0.0
    desired_pitch: float = 0.0
    desired_roll: float = 0.0
    desired_yaw: float = 0.0
    desired_depth: float = 0.0
    auto_tuning_active: bool = False
    auto_tuning_start_time: float = 0.0
