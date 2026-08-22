"""Typed, process-wide ESC firmware state for the mock WebSocket server."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any

from rov_firmware.models.system import (
    EscFirmwareUpdate,
    EscFirmwareUpdateOrigin,
    EscFirmwareUpdateStage,
)


ESC_FLASH_TOAST_ID = "flash-esc-firmware"
PERCENT_COMPLETE = 100
ESC_COUNT = 8
ESC_UPLOAD_PERCENT = 10
ESC_PROGRAM_PERCENT = PERCENT_COMPLETE - ESC_UPLOAD_PERCENT
TARGET_VERSION = "2.21.0-rc.1"
INITIAL_VERSION = "2.20.0-rc.1"

MockMessageSender = Callable[[dict[str, Any]], Awaitable[None]]


class MockEscFirmware:
    """Simulate one process-wide ESC update with telemetry-owned versions."""

    def __init__(self, *, flash_duration_seconds: float = 3.0) -> None:
        """Initialize isolated update state with a configurable test duration."""
        self.flash_duration_seconds = flash_duration_seconds
        self.update = EscFirmwareUpdate()
        self.versions: list[str | None] = [INITIAL_VERSION] * ESC_COUNT
        self._task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def active(self) -> bool:
        """Return whether the shared simulation task is running."""
        return self._task is not None and not self._task.done()

    def status_payload(self) -> tuple[list[str | None], dict[str, Any]]:
        """Observe telemetry and return the serialized status contract."""
        if (
            self.update.stage == EscFirmwareUpdateStage.AWAITING_TELEMETRY
            and self.update.target_version is not None
            and all(version == self.update.target_version for version in self.versions)
        ):
            self.update.stage = EscFirmwareUpdateStage.SUCCEEDED
        return (
            list(self.versions),
            self.update.model_dump(by_alias=True, mode="json"),
        )

    async def start(self, send_message: MockMessageSender) -> bool:
        """Start one shared update, rejecting any overlapping request."""
        if self.active:
            return False
        self._task = asyncio.create_task(self._run(send_message))
        return True

    async def shutdown(self) -> None:
        """Cancel and await the shared simulation task."""
        if not self.active or self._task is None:
            return
        _ = self._task.cancel()
        _ = await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, send_message: MockMessageSender) -> None:
        try:
            self.update = EscFirmwareUpdate(
                active=True,
                origin=EscFirmwareUpdateOrigin.MANUAL,
                stage=EscFirmwareUpdateStage.PREFLIGHT,
                target_version=TARGET_VERSION,
            )
            start_time = time.monotonic()
            last_percent = -1

            while True:
                elapsed = time.monotonic() - start_time
                percent = min(
                    PERCENT_COMPLETE,
                    int((elapsed / self.flash_duration_seconds) * PERCENT_COMPLETE),
                )
                if percent != last_percent:
                    last_percent = percent
                    motor = None
                    if percent >= ESC_UPLOAD_PERCENT:
                        motor = min(
                            ESC_COUNT - 1,
                            ((percent - ESC_UPLOAD_PERCENT) * ESC_COUNT)
                            // ESC_PROGRAM_PERCENT,
                        )
                    self.update.stage = (
                        EscFirmwareUpdateStage.UPLOADING
                        if motor is None
                        else EscFirmwareUpdateStage.PROGRAMMING
                    )
                    self.update.progress = percent
                    self.update.current_esc = None if motor is None else motor + 1
                    await send_message(self._progress_toast(percent, motor))

                if percent >= PERCENT_COMPLETE:
                    break
                await asyncio.sleep(0.05)

            self.update.active = False
            self.update.stage = EscFirmwareUpdateStage.AWAITING_TELEMETRY
            self.update.progress = PERCENT_COMPLETE
            self.update.current_esc = None
            self.versions = [TARGET_VERSION] * ESC_COUNT
            await send_message(self._success_toast())
            self._logger.info("Mock ESC firmware flash complete")
        except asyncio.CancelledError:
            self.update.active = False
            self.update.stage = EscFirmwareUpdateStage.FAILED
            self.update.error = "Mock update cancelled"
            raise
        except Exception:
            self.update.active = False
            self.update.stage = EscFirmwareUpdateStage.FAILED
            self.update.error = "Mock update failed"
            self._logger.exception("Error in mock ESC firmware flash")

    @staticmethod
    def _progress_toast(percent: int, motor: int | None) -> dict[str, Any]:
        return {
            "type": "showToast",
            "payload": {
                "identifier": ESC_FLASH_TOAST_ID,
                "variant": "loading",
                "content": {
                    "messageKey": "toasts_esc_flash_in_progress",
                    "messageArgs": {"percent": percent},
                    "descriptionKey": (
                        "toasts_esc_flash_uploading"
                        if motor is None
                        else "toasts_esc_flash_motor_progress"
                    ),
                    "descriptionArgs": (
                        None
                        if motor is None
                        else {"esc": motor + 1, "total": ESC_COUNT}
                    ),
                },
                "action": None,
            },
        }

    @staticmethod
    def _success_toast() -> dict[str, Any]:
        return {
            "type": "showToast",
            "payload": {
                "identifier": ESC_FLASH_TOAST_ID,
                "variant": "success",
                "content": {"messageKey": "toasts_esc_flash_success"},
                "action": None,
            },
        }
