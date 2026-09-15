"""Central state management for the ROV firmware."""

import asyncio
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .pico_control import PicoControl

from .esc_recovery import recovery_journal_exists
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
        recovery_required = recovery_journal_exists()
        self.esc_firmware_update: EscFirmwareUpdate = EscFirmwareUpdate(
            recovery_required=recovery_required
        )
        self.imu: ImuData = ImuData()
        self.pressure: PressureData = PressureData()
        self.mcu_telemetry: McuData = McuData()
        self.regulator: RegulatorData = RegulatorData()
        self.thrusters: ThrusterData = ThrusterData()
        self.mcu_flashing: bool = False
        self.esc_firmware_recovery_required: bool = recovery_required
        self.esc_firmware_confirmation_deadline: float | None = None
        self.esc_firmware_confirmation_toasts: bool = False
        self.config_ack_waiters: dict[str, asyncio.Future[None]] = {}
        self.connection_change_task: asyncio.Task[None] | None = None
        self.config_confirmation_tasks: set[asyncio.Task[None]] = set()
        self.mcu_flash_lock = asyncio.Lock()
        self.config_mutation_lock = asyncio.Lock()
        self.pico: PicoControl | None = None

    async def set_desired_attitude(
        self, quaternion: tuple[float, float, float, float]
    ) -> None:
        """Await actual Pico apply of absolute body-to-world XYZW for custom actions."""
        if self.pico is None:
            msg = "Pico control is unavailable"
            raise ConnectionError(msg)
        await self.pico.set_desired_attitude(quaternion)

    async def set_desired_depth(self, depth: float) -> None:
        """Await actual Pico apply before changing the local target projection."""
        if self.pico is None:
            msg = "Pico control is unavailable"
            raise ConnectionError(msg)
        await self.pico.set_desired_depth(depth)
