from __future__ import annotations
from typing import Optional

from .models.config import RovConfig
from .models.sensors import ImuData, PressureData
from .models.system import SystemHealth, SystemStatus
from .models.regulator import RegulatorData
from .models.esc import EscData
from numpy.typing import NDArray
import numpy as np


class RovState:
    rov_config: RovConfig
    system_health: SystemHealth
    system_status: SystemStatus
    imu: ImuData
    pressure: PressureData
    esc: EscData
    regulator: RegulatorData
    direction_vector: Optional[NDArray[np.float64]]
    last_direction_time: float

    def __init__(self) -> None:
        self.rov_config = RovConfig.load()
        self.system_health = SystemHealth()
        self.system_status = SystemStatus()
        self.imu = ImuData()
        self.pressure = PressureData()
        self.esc = EscData()
        self.regulator = RegulatorData()
        self.direction_vector = None
        self.last_direction_time = 0.0
