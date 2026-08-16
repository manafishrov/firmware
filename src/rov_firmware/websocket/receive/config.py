"""WebSocket config handlers for the ROV firmware."""

import asyncio
import shutil
import subprocess
from typing import Any

from pydantic import ValidationError

from ...log import log_info, log_warn
from ...models.config import PartialRovConfig, RovConfig, apply_migrations
from ...rov_state import RovState
from ...toast import ToastContent, toast_info, toast_success, toast_warn
from ..message import Config
from ..queue import get_message_queue


_DEVICE_REPORTED_FIELDS = ("firmwareVersion",)
_APPLY_COMMAND_TIMEOUT_SECONDS = 10.0
_SYSTEMCTL_TIMEOUT_SECONDS = 5.0


async def handle_get_config(
    state: RovState,
) -> None:
    """Handle get config request.

    Args:
        state: The ROV state.
    """
    await get_message_queue().put(Config(payload=state.rov_config))
    log_info("Sent config to client.")


def _run_apply_command(binary: str, success_message: str, failure_message: str) -> bool:
    """Run a bounded system configuration helper and report its result."""
    path = shutil.which(binary)
    if path is None:
        log_warn(f"{binary} not found in PATH.")
        return False
    try:
        subprocess.run(  # noqa: S603
            [path],
            check=True,
            capture_output=True,
            timeout=_APPLY_COMMAND_TIMEOUT_SECONDS,
        )
        log_info(success_message)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        log_warn(f"{failure_message}: {error}")
        return False


def _apply_ip_address(ip_address: str) -> bool:
    return _run_apply_command(
        "manafish-network",
        f"Applied IP address change to {ip_address}.",
        f"Failed to apply IP address change to {ip_address}",
    )


async def _restart_firmware() -> bool:
    path = shutil.which("systemctl")
    if path is None:
        log_warn("systemctl not found in PATH.")
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            "try-restart",
            "--no-block",
            "manafish-firmware.service",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        log_warn(f"Failed to start systemctl: {error}.")
        return False

    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_SYSTEMCTL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        log_warn("Timed out while requesting the firmware restart.")
        return False

    if process.returncode != 0:
        details = stderr.decode(errors="replace").strip()
        suffix = f": {details}" if details else "."
        log_warn(f"Failed to restart firmware after the WebSocket port change{suffix}")
        return False

    log_info("Restarting firmware to apply the WebSocket port change.")
    return True


async def _apply_connection_change(
    state: RovState,
    previous_config: RovConfig,
) -> bool:
    """Apply connection settings, restoring the persisted config on failure."""
    ip_changed = state.rov_config.ip_address != previous_config.ip_address
    port_changed = state.rov_config.websocket_port != previous_config.websocket_port
    if not ip_changed and not port_changed:
        return True

    if ip_changed:
        toast_info(
            identifier=None,
            content=ToastContent(message_key="toasts_rov_ip_address_changing"),
            action=None,
        )
        applied = await asyncio.to_thread(
            _apply_ip_address,
            state.rov_config.ip_address,
        )
    else:
        applied = await _restart_firmware()

    if applied:
        return True

    failed_ip = state.rov_config.ip_address
    state.rov_config = previous_config
    state.rov_config.save()
    log_warn("Restored the previous ROV connection config after apply failure.")

    if ip_changed:
        rollback_applied = await asyncio.to_thread(
            _apply_ip_address,
            previous_config.ip_address,
        )
        if not rollback_applied:
            log_warn(
                f"Could not restore network address {previous_config.ip_address} "
                f"after failed change to {failed_ip}."
            )

    toast_warn(
        identifier=None,
        content=ToastContent(message_key="toasts_rov_connection_restart_failed"),
        action=None,
    )
    return False


def _apply_camera() -> None:
    _run_apply_command(
        "manafish-camera",
        "Applied camera settings and restarted the video stream.",
        "Failed to apply camera settings",
    )


async def handle_set_config(
    state: RovState,
    payload: PartialRovConfig,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: Partial ROV configuration update.
    """
    previous_config = state.rov_config.model_copy(deep=True)
    previous_camera = previous_config.camera
    current_data = state.rov_config.model_dump(by_alias=False)
    update_data = payload.model_dump(by_alias=False, include=payload.model_fields_set)
    if payload.camera is not None:
        camera_update = payload.camera.model_dump(
            by_alias=False,
            include=payload.camera.model_fields_set,
        )
        update_data["camera"] = {**current_data["camera"], **camera_update}
    current_data.update(update_data)
    state.rov_config = RovConfig.model_validate(current_data)
    state.rov_config.save()
    log_info("Received and applied config update.")
    if not await _apply_connection_change(state, previous_config):
        await get_message_queue().put(Config(payload=state.rov_config))
        return

    await get_message_queue().put(Config(payload=state.rov_config))
    if state.rov_config.camera != previous_camera:
        _apply_camera()

    toast_success(
        identifier=None,
        content=ToastContent(
            message_key="toasts_rov_config_set_successfully",
        ),
        action=None,
    )


def _strip_device_reported(raw: dict[str, Any]) -> None:
    for key in _DEVICE_REPORTED_FIELDS:
        raw.pop(key, None)


def _tolerant_merge(
    base: dict[str, Any],
    raw: dict[str, Any],
) -> tuple[RovConfig, list[str]]:
    working = dict(base)
    skipped: list[str] = []
    for key, value in raw.items():
        candidate = {**working, key: value}
        try:
            RovConfig.model_validate(candidate)
        except ValidationError:
            skipped.append(key)
            continue
        working = candidate
    return RovConfig.model_validate(working), skipped


async def handle_import_config(
    state: RovState,
    payload: dict[str, Any],
) -> None:
    """Handle a raw config import without enforcing the current schema.

    Args:
        state: The ROV state.
        payload: Raw config dictionary from the app, possibly from an older or
            newer firmware version.
    """
    previous_config = state.rov_config.model_copy(deep=True)
    previous_camera = previous_config.camera
    migration_input = dict(payload)
    board_was_omitted = "mcuBoard" not in migration_input
    if board_was_omitted:
        migration_input["mcuBoard"] = state.rov_config.mcu_board.value
    raw = apply_migrations(migration_input)
    if board_was_omitted:
        raw.pop("mcuBoard", None)
    _strip_device_reported(raw)

    current = state.rov_config.model_dump(by_alias=True)
    if isinstance(raw.get("camera"), dict):
        raw["camera"] = {**current["camera"], **raw["camera"]}
    merged = {**current, **raw}

    try:
        new_config = RovConfig.model_validate(merged)
        skipped: list[str] = []
    except ValidationError:
        new_config, skipped = _tolerant_merge(current, raw)

    new_config.firmware_version = state.rov_config.firmware_version
    state.rov_config = new_config
    state.rov_config.save()
    log_info(
        f"Imported config from app. Skipped fields: {skipped or 'none'}.",
    )
    if not await _apply_connection_change(state, previous_config):
        await get_message_queue().put(Config(payload=state.rov_config))
        return

    await get_message_queue().put(Config(payload=state.rov_config))
    if state.rov_config.camera != previous_camera:
        _apply_camera()

    if skipped:
        toast_warn(
            identifier=None,
            content=ToastContent(
                message_key="toasts_rov_config_imported_partial",
                message_args={
                    "count": len(skipped),
                    "fields": ", ".join(skipped),
                },
            ),
            action=None,
        )
        return

    toast_success(
        identifier=None,
        content=ToastContent(message_key="toasts_rov_config_imported"),
        action=None,
    )
