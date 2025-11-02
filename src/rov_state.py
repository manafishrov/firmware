"""Central state management for the ROV firmware."""

from __future__ import annotations

from .models.config import RovConfig
from .models.regulator import RegulatorData
from .models.sensors import EscData, ImuData, PressureData
from .models.system import SystemHealth, SystemStatus
from .models.thruster import ThrusterData


class RovState:
    """Central state class for the ROV."""

    rov_config: RovConfig
    system_health: SystemHealth
    system_status: SystemStatus
    imu: ImuData
    pressure: PressureData
    esc: EscData
    regulator: RegulatorData
    thrusters: ThrusterData

    def __init__(self) -> None:
        """Initialize the ROV state."""
        self.rov_config: RovConfig = RovConfig.load()
        self.system_health: SystemHealth = SystemHealth()
        self.system_status: SystemStatus = SystemStatus()
        self.imu: ImuData = ImuData()
        self.pressure: PressureData = PressureData()
        self.esc: EscData = EscData()
        self.regulator: RegulatorData = RegulatorData()
        self.thrusters: ThrusterData = ThrusterData()
