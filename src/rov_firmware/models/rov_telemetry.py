"""ROV telemetry data models for the ROV firmware."""

from .base import CamelCaseModel


class RovTelemetry(CamelCaseModel):
    """Model for ROV telemetry."""

    pitch: float
    roll: float
    yaw: float
    depth: float
    desired_pitch: float
    desired_roll: float
    desired_yaw: float
    desired_depth: float
    water_temperature: float
    electronics_temperature: float
    thruster_rpms: list[int]
    work_indicator_percentage: int
