"""System data models for the ROV firmware."""

from pydantic import BaseModel

from .base import CamelCaseModel


class SystemHealth(CamelCaseModel):
    """Model for system health."""

    imu_healthy: bool = False
    pressure_sensor_healthy: bool = False
    microcontroller_healthy: bool = False


class SystemStatus(BaseModel):
    """Model for system status."""

    auto_stabilization: bool = False
    depth_hold: bool = False
    battery_percentage: float = 0
