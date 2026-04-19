"""Serial communication manager for the ROV firmware."""

import asyncio
import contextlib
from pathlib import Path

from serial_asyncio_fast import open_serial_connection

from .constants import MCU_FIRST_BOOT_RETRY_LIMIT
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
        self._first_boot_retries: int = 0
        self._first_boot_flashed: bool = False

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

    async def shutdown(self) -> None:
        """Shutdown the serial connection."""
        async with self._connection_lock:
            await self._clear_connection_unlocked()
