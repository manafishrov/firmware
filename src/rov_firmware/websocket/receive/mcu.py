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
from ...motor_safety import disruptive_motor_operation_blocker
from ...rov_state import RovState
from ...toast import toast_error, toast_loading, toast_success
from ...version import is_valid_semver, semver_sort_key


_BOARD_PREFIXES: dict[McuBoard, str] = {
    McuBoard.PICO: "pico",
    McuBoard.PICO2: "pico2",
}
_COMPLETE_PERCENT = 100


def mcu_versions_match(reported: str, bundled: str) -> bool:
    """Compare the MCU's live release identity with a bundled version."""
    return reported == bundled and is_valid_semver(reported)


def mcu_update_required(reported: str, bundled: str) -> bool:
    """Return whether the bundled image still needs to be loaded on the board."""
    return not mcu_versions_match(reported, bundled)


def resolve_mcu_firmware(board: McuBoard) -> tuple[Path, str] | None:
    """Resolve the versioned .uf2 firmware path and version for a board.

    Returns:
        ``(path, version)`` or ``None`` if no firmware file found.
    """
    prefix = _BOARD_PREFIXES[board]
    mcu_dir = Path.home() / "mcu-firmware"
    candidates: list[tuple[Path, str]] = []
    for firmware_path in mcu_dir.glob(f"{prefix}-v*.uf2"):
        match = re.match(rf"^{re.escape(prefix)}-v(.+)\.uf2$", firmware_path.name)
        if match is not None and is_valid_semver(match.group(1)):
            candidates.append((firmware_path, match.group(1)))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: semver_sort_key(candidate[1]))


def _report_flash_error(
    message: str,
    *,
    show_toasts: bool,
    unexpected: bool = False,
    toast_identifier: str = FLASH_TOAST_ID,
) -> None:
    log_error(message)
    if show_toasts:
        toast_error(
            identifier=toast_identifier,
            content=ToastContent(
                message_key=(
                    "toasts_flash_unexpected_error"
                    if unexpected
                    else "toasts_flash_failed"
                ),
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


def _process_flash_output(
    process: subprocess.Popen[str], toast_identifier: str, show_toasts: bool
) -> tuple[int, str, bool]:
    if process.stdout is None:
        return -1, "", False

    all_output: list[str] = []
    percent = 0
    verification_reached_100 = False
    verification_succeeded = False
    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            line = output.rstrip()
            all_output.append(line)
            percent = _update_load_progress(
                line,
                percent,
                toast_identifier,
                show_toasts=show_toasts,
            )
            verification_reached_100, verification_succeeded = (
                _update_verification_status(
                    line,
                    verification_reached_100,
                    verification_succeeded,
                )
            )

    return (
        cast(int, process.poll()),
        "\n".join(all_output),
        verification_succeeded,
    )


def _picotool_progress(line: str, prefix: str) -> int | None:
    if prefix not in line:
        return None
    match = re.search(r"(\d+)%", line)
    return int(match.group(1)) if match else None


def _update_load_progress(
    line: str,
    percent: int,
    toast_identifier: str,
    *,
    show_toasts: bool,
) -> int:
    new_percent = _picotool_progress(line, "Loading into Flash:")
    if new_percent is None or new_percent == percent:
        return percent
    if show_toasts:
        toast_loading(
            identifier=toast_identifier,
            content=ToastContent(
                message_key="toasts_flash_in_progress",
                message_args={"percent": new_percent},
            ),
            action=None,
        )
    return new_percent


def _update_verification_status(
    line: str,
    reached_100: bool,
    succeeded: bool,
) -> tuple[bool, bool]:
    verification_percent = _picotool_progress(line, "Verifying Flash:")
    if verification_percent is not None and verification_percent >= _COMPLETE_PERCENT:
        reached_100 = True
    if reached_100 and line.strip() == "OK":
        succeeded = True
    return reached_100, succeeded


def _flash_write_completed(return_code: int, verification_succeeded: bool) -> bool:
    """Accept a verified write even if picotool failed only while executing it."""
    return return_code == 0 or verification_succeeded


async def flash_mcu_firmware(  # noqa: PLR0911 - each flash phase has a fail-closed exit
    state: RovState,
    board: McuBoard,
    *,
    show_toasts: bool = True,
    toast_identifier: str = FLASH_TOAST_ID,
) -> bool:
    """Flash MCU firmware for the given board.

    Args:
        state: The ROV state.
        board: The board-specific firmware target to flash.
        show_toasts: Whether to show UI toasts for progress/result.
        toast_identifier: Toast identifier to update while flashing.

    Returns:
        True if flash succeeded, False otherwise.
    """
    if state.mcu_flash_lock.locked():
        log_warn("Ignoring MCU flash request because another flash is already running.")
        return False

    blocker = disruptive_motor_operation_blocker(state)
    if blocker is not None:
        _report_flash_error(
            f"Firmware flash is blocked because {blocker}.",
            show_toasts=show_toasts,
            toast_identifier=toast_identifier,
        )
        return False

    async with state.mcu_flash_lock:
        resolved = resolve_mcu_firmware(board)
        if resolved is None:
            _report_flash_error(
                f"Firmware flash failed: no firmware file found for {board.value}",
                show_toasts=show_toasts,
                toast_identifier=toast_identifier,
            )
            return False
        firmware_path, _firmware_version = resolved
        picotool_path = _resolve_picotool_path()

        log_info(f"Flashing firmware '{board.value}' from {firmware_path}")
        try:
            if picotool_path is None:
                _report_flash_error(
                    "Firmware flash failed: picotool not found",
                    show_toasts=show_toasts,
                    toast_identifier=toast_identifier,
                )
                return False

            state.mcu_flashing = True
            state.system_status.thruster_control_ready = False
            state.thrusters.direction_vector = None
            process = subprocess.Popen(  # noqa: S603
                [picotool_path, "load", "-f", "-v", "-x", str(firmware_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            loop = asyncio.get_running_loop()
            rc, output, verification_succeeded = await loop.run_in_executor(
                None,
                _process_flash_output,
                process,
                toast_identifier,
                show_toasts,
            )

            if _flash_write_completed(rc, verification_succeeded):
                if rc != 0:
                    log_warn(
                        f"picotool returned {rc} after verifying the flashed image; "
                        "treating the write as successful because only the subsequent "
                        "execute/reconnect step failed."
                    )
                log_info("Firmware flash succeeded.")
                if show_toasts:
                    toast_success(
                        identifier=toast_identifier,
                        content=ToastContent(message_key="toasts_flash_success"),
                        action=None,
                    )
                return True

            _report_flash_error(
                f"Firmware flash failed (rc={rc}):\n{output}",
                show_toasts=show_toasts,
                toast_identifier=toast_identifier,
            )
            return False
        except Exception as ex:
            _report_flash_error(
                f"Unexpected firmware flash error: {ex}",
                show_toasts=show_toasts,
                unexpected=True,
                toast_identifier=toast_identifier,
            )
            return False
        finally:
            state.mcu_flashing = False


async def handle_flash_mcu_firmware(
    state: RovState,
    payload: McuBoard,
) -> None:
    """Handle flashing MCU firmware from websocket command."""
    _ = await flash_mcu_firmware(state, payload, show_toasts=True)
