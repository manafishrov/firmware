from __future__ import annotations

from .models.config import RovConfig
from .models.sensors import ImuData, PressureData
from .models.system import SystemHealth, SystemStatus
from .models.regulator import RegulatorData
from .models.esc import EscData


class RovState:
    rov_config: RovConfig
    system_health: SystemHealth
    system_status: SystemStatus
    imu: ImuData
    pressure: PressureData
    esc: EscData
    regulator: RegulatorData

    def __init__(self) -> None:
        self.rov_config = RovConfig.load()
        self.system_health = SystemHealth()
        self.system_status = SystemStatus()
        self.imu = ImuData()
        self.pressure = PressureData()
        self.esc = EscData()
        self.regulator = RegulatorData()
