"""WebSocket config handlers for the ROV firmware."""

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


_DEVICE_REPORTED_FIELDS = ("firmwareVersion", "mcuFirmwareVersion")


async def handle_get_config(
    state: RovState,
) -> None:
    """Handle get config request.

    Args:
        state: The ROV state.
    """
    await get_message_queue().put(Config(payload=state.rov_config))
    log_info("Sent config to client.")


def _apply_ip_address(ip_address: str) -> None:
    path = shutil.which("manafish-network")
    if path is None:
        log_warn("manafish-network not found in PATH.")
        return
    try:
        subprocess.run(  # noqa: S603
            [path],
            check=True,
            capture_output=True,
        )
        log_info(f"Applied IP address change to {ip_address}.")
    except subprocess.CalledProcessError:
        log_warn(f"Failed to apply IP address change to {ip_address}.")


def _apply_camera() -> None:
    path = shutil.which("manafish-camera")
    if path is None:
        log_warn("manafish-camera not found in PATH.")
        return
    try:
        subprocess.run(  # noqa: S603
            [path],
            check=True,
            capture_output=True,
        )
        log_info("Applied camera settings and restarted the video stream.")
    except subprocess.CalledProcessError:
        log_warn("Failed to apply camera settings.")


async def handle_set_config(
    state: RovState,
    payload: PartialRovConfig,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: Partial ROV configuration update.
    """
    old_ip = state.rov_config.ip_address
    old_camera = state.rov_config.camera
    current_data = state.rov_config.model_dump(by_alias=False)
    update_data = payload.model_dump(by_alias=False, include=payload.model_fields_set)
    current_data.update(update_data)
    state.rov_config = RovConfig.model_validate(current_data)
    state.rov_config.save()
    log_info("Received and applied config update.")

    if state.rov_config.ip_address != old_ip:
        toast_info(
            identifier=None,
            content=ToastContent(
                message_key="toasts_rov_ip_address_changing",
            ),
            action=None,
        )
        _apply_ip_address(state.rov_config.ip_address)

    if state.rov_config.camera != old_camera:
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
    old_ip = state.rov_config.ip_address
    old_camera = state.rov_config.camera
    raw = apply_migrations(dict(payload))
    _strip_device_reported(raw)

    current = state.rov_config.model_dump(by_alias=True)
    merged = {**current, **raw}

    try:
        new_config = RovConfig.model_validate(merged)
        skipped: list[str] = []
    except ValidationError:
        new_config, skipped = _tolerant_merge(current, raw)

    new_config.firmware_version = state.rov_config.firmware_version
    new_config.mcu_firmware_version = state.rov_config.mcu_firmware_version
    state.rov_config = new_config
    state.rov_config.save()
    log_info(
        f"Imported config from app. Skipped fields: {skipped or 'none'}.",
    )

    if state.rov_config.ip_address != old_ip:
        toast_info(
            identifier=None,
            content=ToastContent(message_key="toasts_rov_ip_address_changing"),
            action=None,
        )
        _apply_ip_address(state.rov_config.ip_address)

    if state.rov_config.camera != old_camera:
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
