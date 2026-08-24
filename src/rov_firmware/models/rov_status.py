"""ROV status data models for the ROV firmware."""

from .base import CamelCaseModel
from .system import DeviceInfo, EscFirmwareUpdate, SystemHealth


class RovStatus(CamelCaseModel):
    """Model for ROV status."""

    auto_stabilization: bool
    depth_hold: bool
    battery_percentage: int
    current_draw: int
    pi_undervoltage: bool
    thruster_control_ready: bool
    health: SystemHealth
    device_info: DeviceInfo
    esc_firmware_update: EscFirmwareUpdate
