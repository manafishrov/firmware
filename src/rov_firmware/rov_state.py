"""Central state management for the ROV firmware."""

from .models.config import RovConfig
from .models.regulator import RegulatorData
from .models.sensors import ImuData, McuData, PressureData
from .models.system import SystemHealth, SystemStatus
from .models.thruster import ThrusterData


class RovState:
    """Central state class for the ROV."""

    def __init__(self) -> None:
        """Initialize the ROV state."""
        self.rov_config: RovConfig = RovConfig.load()
        self.system_health: SystemHealth = SystemHealth()
        self.system_status: SystemStatus = SystemStatus()
        self.imu: ImuData = ImuData()
        self.pressure: PressureData = PressureData()
        self.mcu_telemetry: McuData = McuData()
        self.regulator: RegulatorData = RegulatorData()
        self.thrusters: ThrusterData = ThrusterData()
        self.mcu_flashing: bool = False
