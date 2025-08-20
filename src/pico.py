from __future__ import annotations

import subprocess
import os
import re
from log import log_info, log_error, log_warn
from toast import toast_error, toast_warn, toast_loading, toast_success, toast_info

FLASH_TOAST_ID = 'flash-microcontroller-firmware'

async def flash_microcontroller_firmware(firmware_variant: str) -> None:
    if firmware_variant == 'pwm':
        firmware_path = os.path.join(os.path.dirname(__file__), 'pico', 'pwm.uf2')
    elif firmware_variant == 'dshot300':
        firmware_path = os.path.join(os.path.dirname(__file__), 'pico', 'dshot300.uf2')
    else:
        await log_error(f"Unknown firmware variant: {firmware_variant}")
        await toast_error(
            id=None,
            message="Tried to flash unknown firmware variant",
            description=None,
            cancel=None,
        )
        return

    await log_info(f"Flashing firmware '{firmware_variant}' from {firmware_path}")
    try:
        process = subprocess.Popen(
            ['picotool', 'load', '-f', '-x', firmware_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        if process.stdout is None:
            await log_warn("Could not capture process stdout.")
            await toast_warn(
                id=None,
                message="Unable to show firmware flashing progress",
                description=None,
                cancel=None,
            )
            return
        all_output = []
        bootsel_toast_shown = False
        percent = 0
        flash_success = False
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                line = output.rstrip()
                all_output.append(line)

                if not bootsel_toast_shown and "The device was asked to reboot into BOOTSEL mode" in line:
                    bootsel_toast_shown = True
                    await toast_info(
                        id=None,
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
                            await toast_loading(
                                id=FLASH_TOAST_ID,
                                message=f"Flashing firmware... {percent}%",
                                description=None,
                                cancel=None,
                            )
                if "Firmware flashed successfully." in line:
                    flash_success = True
        rc = process.poll()
        result_log = "\n".join(all_output)
        await log_info(result_log)
        if flash_success and rc == 0:
            await toast_success(
                id=FLASH_TOAST_ID,
                message="Firmware flashed successfully",
                description=None,
                cancel=None,
            )
        else:
            await toast_error(
                id=FLASH_TOAST_ID,
                message="Firmware flashing failed",
                description=None,
                cancel=None,
            )
            await log_error(f"Firmware flashing failed with return code {rc}.")
    except Exception as ex:
        await toast_error(
            id=FLASH_TOAST_ID,
            message="Firmware flashing encountered an unexpected error",
            description=None,
            cancel=None,
        )
        await log_error(f"Unexpected error: {ex}")
