from __future__ import annotations

import subprocess
import os
from log import log_info, log_error

async def flash_micro_controller_firmware(firmware_variant: str) -> None:
    if firmware_variant == 'pwm':
        firmware_path = os.path.join(os.path.dirname(__file__), 'pico', 'pwm.uf2')
    elif firmware_variant == 'dshot300':
        firmware_path = os.path.join(os.path.dirname(__file__), 'pico', 'dshot300.uf2')
    else:
        await log_error(f"Unknown firmware variant: {firmware_variant}")
        return

    await log_info(f"Flashing firmware '{firmware_variant}' from {firmware_path} ...")
    try:
        process = subprocess.Popen(
            ['picotool', 'load', '-f', '-x', firmware_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        if process.stdout is None:
            await log_error("Could not capture process stdout.")
            return
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                await log_info(output.rstrip())
        rc = process.poll()
        if rc == 0:
            await log_info("Firmware flashed successfully.")
        else:
            await log_error(f"Firmware flashing failed with return code {rc}.")
    except Exception as ex:
        await log_error(f"Unexpected error: {ex}")
