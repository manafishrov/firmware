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
_MCU_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _version_sort_key(
    version: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    """Return a SemVer-compatible key for bundled MCU firmware versions."""
    match = _MCU_VERSION_RE.fullmatch(version)
    if match is None:
        return (-1, -1, -1, -1, ())

    prerelease = match.group("prerelease")
    prerelease_key: tuple[tuple[int, int | str], ...] = ()
    if prerelease is not None:
        prerelease_key = tuple(
            (0, int(identifier)) if identifier.isdigit() else (1, identifier)
            for identifier in prerelease.split(".")
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if prerelease is None else 0,
        prerelease_key,
    )


def mcu_versions_match(reported: str, bundled: str) -> bool:
    """Compare the three-part version an MCU can report with a bundled SemVer."""
    match = _MCU_VERSION_RE.fullmatch(bundled)
    if match is None:
        return reported == bundled
    bundled_core = ".".join(match.group(name) for name in ("major", "minor", "patch"))
    return reported == bundled_core


def mcu_update_required(board: McuBoard, reported: str, bundled: str) -> bool:
    """Return whether the bundled image still needs to be loaded on the board."""
    if not mcu_versions_match(reported, bundled):
        return True
    marker = Path.home() / "mcu-firmware" / f".{_BOARD_PREFIXES[board]}-flashed-version"
    try:
        return marker.read_text(encoding="utf-8").strip() != bundled
    except OSError:
        # A stable image may already be installed because its full version is
        # identical to the three-part version the MCU reports. Prereleases need
        # the marker because their suffix cannot be read back from the MCU.
        return "-" in bundled


def _record_flashed_version(board: McuBoard, version: str) -> None:
    marker = Path.home() / "mcu-firmware" / f".{_BOARD_PREFIXES[board]}-flashed-version"
    try:
        marker.write_text(f"{version}\n", encoding="utf-8")
    except OSError as error:
        log_warn(f"Could not record flashed MCU version: {error}")


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
        if match is not None and _MCU_VERSION_RE.fullmatch(match.group(1)) is not None:
            candidates.append((firmware_path, match.group(1)))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: _version_sort_key(candidate[1]))


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


def _process_flash_output(
    process: subprocess.Popen[str], toast_identifier: str
) -> tuple[int, str]:
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
                            identifier=toast_identifier,
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

    async with state.mcu_flash_lock:
        resolved = resolve_mcu_firmware(board)
        if resolved is None:
            _report_flash_error(
                f"Firmware flash failed: no firmware file found for {board.value}",
                show_toasts=show_toasts,
                toast_identifier=toast_identifier,
            )
            return False
        firmware_path, firmware_version = resolved
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
            process = subprocess.Popen(  # noqa: S603
                [picotool_path, "load", "-f", "-x", str(firmware_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            loop = asyncio.get_running_loop()
            rc, output = await loop.run_in_executor(
                None, _process_flash_output, process, toast_identifier
            )

            if rc == 0:
                _record_flashed_version(board, firmware_version)
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
