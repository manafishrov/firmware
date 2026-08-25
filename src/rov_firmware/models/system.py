"""System data models for the ROV firmware."""

from enum import StrEnum

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


class EscFirmwareUpdateStage(StrEnum):
    """Observable stage of the most recent ESC firmware update."""

    IDLE = "idle"
    PREFLIGHT = "preflight"
    UPLOADING = "uploading"
    PROGRAMMING = "programming"
    AWAITING_TELEMETRY = "awaitingTelemetry"
    SUCCEEDED = "succeeded"
    UNCONFIRMED = "unconfirmed"
    VERSION_MISMATCH = "versionMismatch"
    FAILED = "failed"


class EscFirmwareUpdate(CamelCaseModel):
    """Live ESC firmware update state exposed to the desktop app."""

    active: bool = False
    stage: EscFirmwareUpdateStage = EscFirmwareUpdateStage.IDLE
    progress: int = 0
    current_esc: int | None = None
    target_version: str | None = None
    error: str | None = None
    recovery_required: bool = False


class SystemStatus(BaseModel):
    """Model for system status."""

    auto_stabilization: bool = False
    depth_hold: bool = False
    battery_percentage: float = 0
    thruster_control_ready: bool = False
