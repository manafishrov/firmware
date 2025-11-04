"""ROV telemetry data models for the ROV firmware."""

from .base import CamelCaseModel


class RovTelemetry(CamelCaseModel):
    """Model for ROV telemetry."""

    pitch: float
    roll: float
    desired_pitch: float
    desired_roll: float
    thruster_rpms: list[int]
    work_indicator_percentage: float
