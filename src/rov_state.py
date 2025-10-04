from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models.config import RovConfig
    from .models.sensors import ImuData, PressureData
    from .models.system import SystemHealth, SystemStatus
    from .models.regulator import RegulatorData


class RovState:
    rov_config: RovConfig
    system_health: SystemHealth
    system_status: SystemStatus
    imu: ImuData
    pressure: PressureData
    regulator: RegulatorData

    def __init__(self) -> None:
        self.rov_config = RovConfig.load()
        self.system_health = SystemHealth()
        self.system_status = SystemStatus()
        self.imu = ImuData()
        self.pressure = PressureData()
        self.regulator = RegulatorData()

    def set_config(self, new_config_data: dict) -> None:
        new_config = RovConfig(**new_config_data)
        new_config.save()
        self.rov_config = new_config
