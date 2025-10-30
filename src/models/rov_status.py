"""ROV status data models for the ROV firmware."""

from .base import CamelCaseModel


class RovStatus(CamelCaseModel):
    """Model for ROV status."""

    pitch_stabilization: bool
    roll_stabilization: bool
    depth_hold: bool
    battery_percentage: int
