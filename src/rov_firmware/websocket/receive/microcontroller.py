"""WebSocket microcontroller handlers for the ROV firmware."""

import asyncio
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
from ...rov_state import RovState
from ...toast import toast_error, toast_loading, toast_success


def _flash_error(message: str, *, unexpected: bool = False) -> None:
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


def _process_flash_output(process: subprocess.Popen[str]) -> tuple[int, str]:
    if process.stdout is None:
        return -1, ""

    all_output: list[str] = []
    percent = 0
    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            line = output.rstrip()
            all_output.append(line)

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

    return cast(int, process.poll()), "\n".join(all_output)


async def handle_flash_microcontroller_firmware(
    state: RovState,
    payload: MicrocontrollerFirmwareVariant,
) -> None:
    """Handle flashing microcontroller firmware.

    Args:
        state: The ROV state.
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
            _flash_error("Firmware flash failed: picotool not found")
            return
        if not firmware_path.is_file():
            _flash_error(f"Firmware flash failed: {firmware_path} not found")
            return

        state.microcontroller_flashing = True
        process = subprocess.Popen(  # noqa: S603
            [picotool_path, "load", "-f", "-x", str(firmware_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        loop = asyncio.get_running_loop()
        rc, output = await loop.run_in_executor(None, _process_flash_output, process)

        if rc == 0:
            toast_success(
                identifier=FLASH_TOAST_ID,
                content=ToastContent(message_key="toasts_flash_success"),
                action=None,
            )
        else:
            _flash_error(f"Firmware flash failed (rc={rc}):\n{output}")
    except Exception as ex:
        _flash_error(f"Unexpected firmware flash error: {ex}", unexpected=True)
    finally:
        state.microcontroller_flashing = False
