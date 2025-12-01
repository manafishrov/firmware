"""WebSocket microcontroller handlers for the ROV firmware."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import cast

from ...constants import FLASH_TOAST_ID
from ...log import log_error, log_info, log_warn
from ...models.config import MicrocontrollerFirmwareVariant
from ...toast import toast_error, toast_info, toast_loading, toast_success, toast_warn


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
            toast_id=None,
            message="Unable to show firmware flashing progress",
            description=None,
            cancel=None,
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
                    toast_id=None,
                    message="Microcontroller was asked to reboot into BOOTSEL mode",
                    description=None,
                    cancel=None,
                )
            if "Loading into Flash:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    new_percent = int(match.group(1))
                    if new_percent != percent:
                        percent = new_percent
                        toast_loading(
                            toast_id=FLASH_TOAST_ID,
                            message=f"Flashing firmware... {percent}%",
                            description=None,
                            cancel=None,
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
    firmware_path = (
        Path(__file__).parent / "microcontroller_firmware" / firmware_paths[payload]
    )

    log_info(f"Flashing firmware '{payload.value}' from {firmware_path}")
    try:
        process = subprocess.Popen(  # noqa: S603
            ["picotool", "load", "-f", "-x", firmware_path],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        flash_success, rc = _process_flash_output(process)
        if flash_success and rc == 0:
            toast_success(
                toast_id=FLASH_TOAST_ID,
                message="Firmware flashed successfully",
                description=None,
                cancel=None,
            )
        else:
            toast_error(
                toast_id=FLASH_TOAST_ID,
                message="Firmware flashing failed",
                description=None,
                cancel=None,
            )
            log_error(f"Firmware flashing failed with return code {rc}.")
    except Exception as ex:
        toast_error(
            toast_id=FLASH_TOAST_ID,
            message="Firmware flashing encountered an unexpected error",
            description=None,
            cancel=None,
        )
        log_error(f"Unexpected error: {ex}")
