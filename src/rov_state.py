from __future__ import annotations
from typing import TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from rov_config import ROVConfig
    from imu import IMUData
    from pressure import PressureData


class SystemStatus(BaseModel):
    imu_ok: bool = False
    pressure_sensor_ok: bool = False


class RegulatorData(BaseModel):
    pitch: float
    roll: float
    desired_pitch: float
    desired_roll: float


class ROVState:
    rov_config: ROVConfig
    system_status: SystemStatus
    imu: IMUData
    pressure: PressureData
    regulator: RegulatorData
    pitch_stabilization: bool
    roll_stabilization: bool
    depth_stabilization: bool

    def __init__(self) -> None:
        self.rov_config = ROVConfig.load()
        self.system_status = SystemStatus()
        self.imu = IMUData(acceleration=0.0, gyroscope=0.0, temperature=0.0)
        self.pressure = PressureData(pressure=0.0, temperature=0.0, depth=0.0)
        self.regulator = RegulatorData(
            pitch=0.0,
            roll=0.0,
            desired_pitch=0.0,
            desired_roll=0.0,
        )
        self.pitch_stabilization = False
        self.roll_stabilization = False
        self.depth_stabilization = False

    def set_config(self, config: ROVConfig) -> None:
        self.rov_config = config
        self.rov_config.save()
