"""Serial communication manager for the ROV firmware."""

import asyncio
import contextlib
from pathlib import Path

from serial_asyncio_fast import open_serial_connection

from .constants import (
    MCU_FIRST_BOOT_RETRY_LIMIT,
    MCU_RUNTIME_CONFIG_STATE_APPLIED,
    MCU_RUNTIME_CONFIG_STATE_APPLYING,
    MCU_RUNTIME_CONFIG_STATE_REJECTED,
)
from .log import log_error, log_info, log_warn
from .models.toast import ToastContent
from .rov_state import RovState
from .toast import toast_error


class SerialManager:
    """Serial manager class."""

    def __init__(self, state: RovState):
        """Initialize the serial manager.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._connection_lock: asyncio.Lock = asyncio.Lock()
        self.io_lock: asyncio.Lock = asyncio.Lock()
        self.write_lock: asyncio.Lock = asyncio.Lock()
        self._first_boot_retries: int = 0
        self._first_boot_flashed: bool = False
        self._connection_generation: int = 0
        self._mcu_protocol_config: tuple[str, int] | None = None
        self._mcu_protocol_request_id: int | None = None

    async def _find_mcu_port(self, *, log_missing: bool = True) -> str | None:
        mcu_ports = list(Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*"))
        if not mcu_ports:
            mcu_ports = list(Path("/dev/").glob("ttyACM*"))
        if mcu_ports:
            return str(mcu_ports[0])
        if log_missing:
            log_error("Error: Could not find MCU serial port.")
        return None

    async def _clear_connection_unlocked(self) -> None:
        writer = self.writer
        self.reader = None
        self.writer = None
        self._mcu_protocol_config = None
        self._mcu_protocol_request_id = None
        self.state.system_status.thruster_control_ready = False
        self.state.system_status.thruster_protocol_state = "disconnected"
        self.state.system_status.thruster_protocol_error = None
        self.state.device_info.mcu_firmware_version = ""
        self.state.device_info.mcu_firmware_version_status = "querying"
        self.state.system_health.mcu_healthy = False
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def initialize(self, *, notify: bool = True) -> bool:
        """Initialize the serial connection to the MCU."""
        async with self._connection_lock:
            if self.reader is not None and self.writer is not None:
                self.state.system_health.mcu_healthy = True
                return True

            try:
                if notify:
                    log_info("Attempting to initialize MCU...")
                serial_port = await self._find_mcu_port(log_missing=notify)
                if serial_port is None:
                    await self._clear_connection_unlocked()
                    self._first_boot_retries += 1
                    if (
                        not self._first_boot_flashed
                        and self._first_boot_retries >= MCU_FIRST_BOOT_RETRY_LIMIT
                    ):
                        await self._auto_flash_first_boot()
                    elif notify:
                        log_error("Failed to initialize MCU. Is it connected?")
                        toast_error(
                            identifier=None,
                            content=ToastContent(
                                message_key="toasts_mcu_init_failed",
                                description_key="toasts_mcu_init_failed_description",
                            ),
                            action=None,
                        )
                    return False
                self.reader, self.writer = await open_serial_connection(
                    url=serial_port, baudrate=115200
                )
                self._connection_generation += 1
                self._mcu_protocol_config = None
                self._mcu_protocol_request_id = None
                self.state.system_status.thruster_control_ready = False
                self.state.system_status.thruster_protocol_state = "synchronizing"
                self.state.system_status.thruster_protocol_error = None
                self.state.system_health.mcu_healthy = True
                log_info("MCU initialized successfully.")
                return True
            except Exception as e:
                await self._clear_connection_unlocked()
                log_error(f"Failed to initialize MCU. Is it connected? Error: {e}")
                if notify:
                    toast_error(
                        identifier=None,
                        content=ToastContent(
                            message_key="toasts_mcu_init_failed",
                            description_key="toasts_mcu_init_failed_description",
                        ),
                        action=None,
                    )
                return False

    async def _auto_flash_first_boot(self) -> None:
        from .websocket.receive.mcu import flash_mcu_firmware  # noqa: PLC0415

        if self.state.esc_firmware_recovery_required:
            log_warn("Skipping automatic MCU flash while ESC recovery is required.")
            return
        self._first_boot_flashed = True
        board = self.state.rov_config.mcu_board
        log_warn(
            f"MCU not found after {MCU_FIRST_BOOT_RETRY_LIMIT} attempts. Auto-flashing {board.value} firmware..."
        )
        await flash_mcu_firmware(self.state, board, show_toasts=True)

    async def ensure_connection(self) -> bool:
        """Return whether the MCU serial connection is ready for use."""
        if self.state.mcu_flashing:
            return False
        if self.reader is not None and self.writer is not None:
            self.state.system_health.mcu_healthy = True
            return True
        return await self.initialize(notify=False)

    async def handle_connection_lost(self, reason: str) -> None:
        """Log a serial failure and clear the active MCU connection."""
        async with self._connection_lock:
            if self.reader is None and self.writer is None:
                self.state.system_health.mcu_healthy = False
                return
            if not self.state.mcu_flashing:
                log_error(reason)
            await self._clear_connection_unlocked()

    def get_reader(self) -> asyncio.StreamReader:
        """Get the serial reader."""
        if self.reader is None:
            msg = "Serial not initialized"
            raise RuntimeError(msg)
        return self.reader

    def get_writer(self) -> asyncio.StreamWriter:
        """Get the serial writer."""
        if self.writer is None:
            msg = "Serial not initialized"
            raise RuntimeError(msg)
        return self.writer

    @property
    def connection_generation(self) -> int:
        """Monotonically increasing serial connection generation."""
        return self._connection_generation

    @property
    def mcu_protocol_config(self) -> tuple[str, int] | None:
        """Protocol configuration most recently acknowledged by the MCU."""
        return self._mcu_protocol_config

    def record_mcu_protocol_config(self, protocol: str, dshot_speed: int) -> None:
        """Record a protocol configuration acknowledged by the MCU."""
        self._mcu_protocol_config = (protocol, dshot_speed)
        desired = (
            self.state.rov_config.thruster_protocol.value,
            self.state.rov_config.dshot_speed,
        )
        if self._mcu_protocol_config != desired:
            self.state.system_status.thruster_control_ready = False
            self.state.system_status.thruster_protocol_state = "failed"
            self.state.system_status.thruster_protocol_error = "The thruster protocol reported by the MCU does not match the saved settings."
        elif self.state.esc_firmware_recovery_required:
            self.state.system_status.thruster_control_ready = False
            self.state.system_status.thruster_protocol_state = "failed"
            self.state.system_status.thruster_protocol_error = (
                "ESC firmware recovery is required before thruster control can resume."
            )
        elif self.state.mcu_flashing:
            self.state.system_status.thruster_control_ready = False
            self.state.system_status.thruster_protocol_state = "synchronizing"
            self.state.system_status.thruster_protocol_error = None
        else:
            self.state.system_status.thruster_control_ready = True
            self.state.system_status.thruster_protocol_state = "ready"
            self.state.system_status.thruster_protocol_error = None

    def begin_mcu_protocol_request(self, request_id: int) -> None:
        """Track the current correlated runtime-config request."""
        self._mcu_protocol_request_id = request_id
        self.state.system_status.thruster_control_ready = False
        self.state.system_status.thruster_protocol_state = "applying"
        self.state.system_status.thruster_protocol_error = None

    def record_mcu_protocol_status(
        self,
        request_id: int,
        status: int,
        error: int,
        protocol: str,
        dshot_speed: int,
    ) -> None:
        """Apply a correlated runtime-config state reported by the MCU."""
        if request_id != self._mcu_protocol_request_id:
            return
        if status == MCU_RUNTIME_CONFIG_STATE_APPLYING:
            self.state.system_status.thruster_protocol_state = "applying"
            self.state.system_status.thruster_protocol_error = None
            return
        if status == MCU_RUNTIME_CONFIG_STATE_REJECTED:
            self.state.system_status.thruster_control_ready = False
            self.state.system_status.thruster_protocol_state = "failed"
            errors = {
                1: "The MCU rejected the change because the thrusters were active.",
                2: "ESC firmware recovery is required before thruster control can resume.",
                3: "The MCU is still applying the previous thruster protocol change.",
            }
            self.state.system_status.thruster_protocol_error = errors.get(
                error, f"The MCU rejected the protocol change (error {error})."
            )
            return
        if status == MCU_RUNTIME_CONFIG_STATE_APPLIED:
            self.record_mcu_protocol_config(protocol, dshot_speed)

    def invalidate_mcu_protocol_config(self) -> None:
        """Require a fresh MCU acknowledgement before thruster output resumes."""
        self._mcu_protocol_config = None
        self._mcu_protocol_request_id = None
        self.state.system_status.thruster_control_ready = False
        self.state.system_status.thruster_protocol_state = "synchronizing"
        self.state.system_status.thruster_protocol_error = None

    async def shutdown(self) -> None:
        """Shutdown the serial connection."""
        async with self._connection_lock:
            await self._clear_connection_unlocked()
