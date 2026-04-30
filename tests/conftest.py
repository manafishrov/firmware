import numpy as np
import pytest

from rov_firmware.models.config import RovConfig
from rov_firmware.models.regulator import RegulatorData
from rov_firmware.models.sensors import ImuData, McuData, PressureData
from rov_firmware.models.system import SystemHealth, SystemStatus
from rov_firmware.models.thruster import ThrusterData
from rov_firmware.rov_state import RovState


@pytest.fixture
def rov_state():
    state = RovState.__new__(RovState)
    state.rov_config = RovConfig()
    state.system_health = SystemHealth()
    state.system_status = SystemStatus()
    state.imu = ImuData()
    state.pressure = PressureData()
    state.mcu_telemetry = McuData()
    state.regulator = RegulatorData()
    state.thrusters = ThrusterData(direction_vector=np.zeros(8, dtype=np.float32))
    state.mcu_flashing = False
    state.firmware_uploading = False
    return state
