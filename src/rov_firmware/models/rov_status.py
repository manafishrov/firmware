"""ROV status data models for the ROV firmware."""

from .base import CamelCaseModel
from .system import SystemHealth


class RovStatus(CamelCaseModel):
    """Model for ROV status."""

    auto_stabilization: bool
    depth_hold: bool
    battery_percentage: int
    health: SystemHealth
