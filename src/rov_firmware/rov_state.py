"""Central state management for the ROV firmware."""

import asyncio

from .models.config import RovConfig
from .models.regulator import RegulatorData
from .models.sensors import ImuData, McuData, PressureData
from .models.system import DeviceInfo, EscFirmwareUpdate, SystemHealth, SystemStatus
from .models.thruster import ThrusterData


class RovState:
    """Central state class for the ROV."""

    def __init__(self) -> None:
        """Initialize the ROV state."""
        self.rov_config: RovConfig = RovConfig.load()
        self.system_health: SystemHealth = SystemHealth()
        self.system_status: SystemStatus = SystemStatus()
        self.device_info: DeviceInfo = DeviceInfo()
        self.esc_firmware_update: EscFirmwareUpdate = EscFirmwareUpdate()
        self.imu: ImuData = ImuData()
        self.pressure: PressureData = PressureData()
        self.mcu_telemetry: McuData = McuData()
        self.regulator: RegulatorData = RegulatorData()
        self.thrusters: ThrusterData = ThrusterData()
        self.mcu_flashing: bool = False
        self.mcu_flash_lock = asyncio.Lock()
