"""WebSocket MCU handlers for the ROV firmware."""

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import cast

from ...constants import FLASH_TOAST_ID
from ...log import log_error, log_info, log_warn
from ...models.config import McuBoard
from ...models.toast import ToastContent
from ...rov_state import RovState
from ...toast import toast_error, toast_loading, toast_success


_BOARD_PREFIXES: dict[McuBoard, str] = {
    McuBoard.PICO: "pico",
    McuBoard.PICO2: "pico2",
}


def resolve_mcu_firmware(board: McuBoard) -> tuple[Path, str] | None:
    """Resolve the versioned .uf2 firmware path and version for a board.

    Returns:
        ``(path, version)`` or ``None`` if no firmware file found.
    """
    prefix = _BOARD_PREFIXES[board]
    mcu_dir = Path.home() / "mcu-firmware"
    matches = list(mcu_dir.glob(f"{prefix}-v*.uf2"))
    if not matches:
        return None
    firmware_path = matches[0]
    match = re.match(rf"^{re.escape(prefix)}-v(.+)\.uf2$", firmware_path.name)
    if not match:
        return None
    return firmware_path, match.group(1)


def _report_flash_error(
    message: str, *, show_toasts: bool, unexpected: bool = False
) -> None:
    log_error(message)
    if show_toasts:
        toast_error(
            identifier=FLASH_TOAST_ID,
            content=ToastContent(
                message_key=(
                    "toasts_flash_unexpected_error"
                    if unexpected
                    else "toasts_flash_failed"
                ),
                description_key="toasts_flash_board_hint",
            ),
            action=None,
        )


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


async def flash_mcu_firmware(
    state: RovState,
    board: McuBoard,
    *,
    show_toasts: bool = True,
) -> bool:
    """Flash MCU firmware for the given board.

    Args:
        state: The ROV state.
        board: The board-specific firmware target to flash.
        show_toasts: Whether to show UI toasts for progress/result.

    Returns:
        True if flash succeeded, False otherwise.
    """
    resolved = resolve_mcu_firmware(board)
    if resolved is None:
        _report_flash_error(
            f"Firmware flash failed: no firmware file found for {board.value}",
            show_toasts=show_toasts,
        )
        return False
    firmware_path, _ = resolved
    picotool_path = _resolve_picotool_path()

    log_info(f"Flashing firmware '{board.value}' from {firmware_path}")
    try:
        if picotool_path is None:
            _report_flash_error(
                "Firmware flash failed: picotool not found", show_toasts=show_toasts
            )
            return False

        state.mcu_flashing = True
        process = subprocess.Popen(  # noqa: S603
            [picotool_path, "load", "-f", "-x", str(firmware_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        loop = asyncio.get_running_loop()
        rc, output = await loop.run_in_executor(None, _process_flash_output, process)

        if rc == 0:
            log_info("Firmware flash succeeded.")
            if show_toasts:
                toast_success(
                    identifier=FLASH_TOAST_ID,
                    content=ToastContent(message_key="toasts_flash_success"),
                    action=None,
                )
            return True

        _report_flash_error(
            f"Firmware flash failed (rc={rc}):\n{output}", show_toasts=show_toasts
        )
        return False
    except Exception as ex:
        _report_flash_error(
            f"Unexpected firmware flash error: {ex}",
            show_toasts=show_toasts,
            unexpected=True,
        )
        return False
    finally:
        state.mcu_flashing = False


async def handle_flash_mcu_firmware(
    state: RovState,
    payload: McuBoard,
) -> None:
    """Handle flashing MCU firmware from websocket command."""
    await flash_mcu_firmware(state, payload, show_toasts=True)
