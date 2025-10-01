from __future__ import annotations
from typing import TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from rov_config import ROVConfig
    from imu import IMUData
    from pressure import PressureData


class SystemHealth(BaseModel):
    imu_ok: bool = False
    pressure_sensor_ok: bool = False


class SystemStatus(BaseModel):
    pitch_stabilization: bool = False
    roll_stabilization: bool = False
    depth_stabilization: bool = False


class RegulatorData(BaseModel):
    pitch: float = 0.0
    roll: float = 0.0
    desired_pitch: float = 0.0
    desired_roll: float = 0.0


class ROVState:
    rov_config: ROVConfig
    system_health: SystemHealth
    system_status: SystemStatus
    imu: IMUData
    pressure: PressureData
    regulator: RegulatorData

    def __init__(self) -> None:
        self.rov_config = ROVConfig.load()
        self.system_health = SystemHealth()
        self.system_status = SystemStatus()
        self.imu = IMUData()
        self.pressure = PressureData()
        self.regulator = RegulatorData()

    def set_config(self, new_config_data: dict) -> None:
        new_config = ROVConfig(**new_config_data)
        new_config.save()
        self.rov_config = new_config
