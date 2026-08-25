import asyncio

import numpy as np
import pytest

from rov_firmware import esc_recovery
from rov_firmware.models.config import RovConfig
from rov_firmware.models.regulator import RegulatorData
from rov_firmware.models.sensors import ImuData, McuData, PressureData
from rov_firmware.models.system import (
    DeviceInfo,
    EscFirmwareUpdate,
    SystemHealth,
    SystemStatus,
)
from rov_firmware.models.thruster import ThrusterData
from rov_firmware.rov_state import RovState


@pytest.fixture
def rov_state(monkeypatch, tmp_path):
    monkeypatch.setattr(
        esc_recovery,
        "_RECOVERY_JOURNAL_PATH",
        tmp_path / "esc-firmware-update.json",
    )
    state = RovState.__new__(RovState)
    state.rov_config = RovConfig()
    state.system_health = SystemHealth()
    state.system_status = SystemStatus()
    state.device_info = DeviceInfo()
    state.esc_firmware_update = EscFirmwareUpdate()
    state.imu = ImuData()
    state.pressure = PressureData()
    state.mcu_telemetry = McuData()
    state.regulator = RegulatorData()
    state.thrusters = ThrusterData(direction_vector=np.zeros(8, dtype=np.float32))
    state.mcu_flashing = False
    state.esc_firmware_recovery_required = False
    state.esc_firmware_confirmation_deadline = None
    state.esc_firmware_confirmation_toasts = False
    state.config_ack_waiters = {}
    state.connection_change_task = None
    state.mcu_flash_lock = asyncio.Lock()
    return state
