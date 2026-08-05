"""System data models for the ROV firmware."""

from pydantic import BaseModel, Field

from ..constants import NUM_MOTORS
from .base import CamelCaseModel


class SystemHealth(CamelCaseModel):
    """Model for system health."""

    imu_healthy: bool = False
    pressure_sensor_healthy: bool = False
    mcu_healthy: bool = False


class DeviceInfo(CamelCaseModel):
    """Read-only firmware information reported by connected devices."""

    mcu_firmware_version: str = ""
    esc_firmware_versions: list[str | None] = Field(
        default_factory=lambda: [None] * NUM_MOTORS
    )


class SystemStatus(BaseModel):
    """Model for system status."""

    auto_stabilization: bool = False
    depth_hold: bool = False
    battery_percentage: float = 0
