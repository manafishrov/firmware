"""WebSocket microcontroller handlers for the ROV firmware."""

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import cast

from ...constants import FLASH_TOAST_ID
from ...log import log_error, log_info, log_warn
from ...models.config import MicrocontrollerFirmwareVariant
from ...models.toast import ToastContent
from ...toast import (
    toast_error,
    toast_info,
    toast_loading,
    toast_success,
    toast_warn,
)


def _flash_failed(message: str, *, unexpected: bool = False) -> None:
    toast_error(
        identifier=FLASH_TOAST_ID,
        content=ToastContent(
            message_key=(
                "toasts_flash_unexpected_error" if unexpected else "toasts_flash_failed"
            ),
        ),
        action=None,
    )
    log_error(message)


def _resolve_picotool_path() -> str | None:
    configured_path = os.environ.get("PICOTOOL_PATH")
    if configured_path:
        picotool_path = Path(configured_path)
        if picotool_path.is_file():
            return str(picotool_path)
        log_warn(f"Configured PICOTOOL_PATH does not exist: {configured_path}")

    return shutil.which("picotool")


def _process_flash_output(process: subprocess.Popen[str]) -> tuple[bool, int]:
    """Process the output from the flash process.

    Args:
        process: The subprocess.

    Returns:
        A tuple of (flash_success, return_code).
    """
    if process.stdout is None:
        log_warn("Could not capture process stdout.")
        toast_warn(
            identifier=None,
            content=ToastContent(
                message_key="toasts_flash_progress_unavailable",
            ),
            action=None,
        )
        return False, -1

    all_output: list[str] = []
    bootsel_toast_shown = False
    percent = 0
    flash_success = False
    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            line: str = output.rstrip()
            all_output.append(line)

            if (
                not bootsel_toast_shown
                and "The device was asked to reboot into BOOTSEL mode" in line
            ):
                bootsel_toast_shown = True
                toast_info(
                    identifier=None,
                    content=ToastContent(
                        message_key="toasts_flash_bootsel_requested",
                    ),
                    action=None,
                )
            if "Loading into Flash:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    new_percent = int(match.group(1))
                    if new_percent != percent:
                        percent = new_percent
                        toast_loading(
                            identifier=FLASH_TOAST_ID,
                            content=ToastContent(
                                message_key="toasts_flash_in_progress",
                                message_args={"percent": percent},
                            ),
                            action=None,
                        )
            if "Firmware flashed successfully." in line:
                flash_success = True
    rc = cast(int, process.poll())
    result_log = "\n".join(all_output)
    log_info(result_log)
    return flash_success, rc


async def handle_flash_microcontroller_firmware(
    payload: MicrocontrollerFirmwareVariant,
) -> None:
    """Handle flashing microcontroller firmware.

    Args:
        payload: The firmware variant to flash.
    """
    firmware_paths = {
        MicrocontrollerFirmwareVariant.PWM: "pwm.uf2",
        MicrocontrollerFirmwareVariant.DSHOT: "dshot.uf2",
    }
    firmware_path = Path.home() / "microcontroller-firmware" / firmware_paths[payload]
    picotool_path = _resolve_picotool_path()

    log_info(f"Flashing firmware '{payload.value}' from {firmware_path}")
    try:
        if picotool_path is None:
            _flash_failed(
                "Could not flash microcontroller firmware: picotool not found"
            )
            return
        if not firmware_path.is_file():
            _flash_failed(
                f"Could not flash microcontroller firmware: firmware file not found at {firmware_path}"
            )
            return
        process = subprocess.Popen(  # noqa: S603
            [picotool_path, "load", "-f", "-x", str(firmware_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        flash_success, rc = _process_flash_output(process)
        if flash_success and rc == 0:
            toast_success(
                identifier=FLASH_TOAST_ID,
                content=ToastContent(
                    message_key="toasts_flash_success",
                ),
                action=None,
            )
        else:
            toast_error(
                identifier=FLASH_TOAST_ID,
                content=ToastContent(
                    message_key="toasts_flash_failed",
                ),
                action=None,
            )
            log_error(f"Firmware flashing failed with return code {rc}.")
    except Exception as ex:
        _flash_failed(
            f"Unexpected microcontroller flashing error: {ex}", unexpected=True
        )
