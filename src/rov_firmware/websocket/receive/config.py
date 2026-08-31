"""WebSocket config handlers for the ROV firmware."""

import asyncio
import shutil
import subprocess
from typing import Any

from pydantic import ValidationError

from ...log import log_info, log_warn
from ...models.config import PartialRovConfig, RovConfig, apply_migrations
from ...motor_safety import disruptive_motor_operation_blocker
from ...rov_state import RovState
from ...toast import ToastContent, toast_info, toast_success, toast_warn
from ..message import Config, ConfigPayload
from ..queue import get_message_queue, send_message_and_wait
from ..state import websocket_state


_DEVICE_REPORTED_FIELDS = ("firmwareVersion",)
_APPLY_COMMAND_TIMEOUT_SECONDS = 10.0
_CONFIG_ACK_TIMEOUT_SECONDS = 5.0


async def handle_get_config(
    state: RovState,
) -> None:
    """Handle get config request.

    Args:
        state: The ROV state.
    """
    await get_message_queue().put(_config_message(state))
    log_info("Sent config to client.")


def _run_apply_command(
    binary: str,
    success_message: str,
    failure_message: str,
    *arguments: str,
) -> bool:
    """Run a bounded system configuration helper and report its result."""
    path = shutil.which(binary)
    if path is None:
        log_warn(f"{binary} not found in PATH.")
        return False
    try:
        subprocess.run(  # noqa: S603
            [path, *arguments],
            check=True,
            capture_output=True,
            timeout=_APPLY_COMMAND_TIMEOUT_SECONDS,
        )
        log_info(success_message)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        log_warn(f"{failure_message}: {error}")
        return False


def _connection_changed(current: RovConfig, previous: RovConfig) -> bool:
    return (
        current.ip_address != previous.ip_address
        or current.websocket_port != previous.websocket_port
    )


def _connection_restart_message_key(current: RovConfig, previous: RovConfig) -> str:
    if current.ip_address != previous.ip_address:
        return "toasts_rov_connection_restart_required"
    return "toasts_rov_connection_settings_restart_required"


def _config_message(state: RovState, mutation_id: str | None = None) -> Config:
    return Config(
        payload=ConfigPayload(
            mutation_id=mutation_id,
            config=state.rov_config,
        )
    )


async def _restore_after_config_send_failure(
    state: RovState,
    previous_config: RovConfig,
    error: Exception,
    mutation_id: str | None,
) -> None:
    state.rov_config = previous_config
    state.rov_config.save()
    log_warn(
        f"Did not apply connection settings because config acknowledgement failed: {error}"
    )
    await get_message_queue().put(_config_message(state, mutation_id))
    toast_warn(
        identifier=None,
        content=ToastContent(message_key="toasts_rov_connection_restart_failed"),
        action=None,
    )


async def _await_connection_config_ack(  # noqa: PLR0913 - rollback inputs stay explicit
    state: RovState,
    previous_config: RovConfig,
    mutation_id: str,
    ack: asyncio.Future[None],
    camera_changed: bool,
    success_message_key: str,
    restart_message_key: str,
) -> None:
    try:
        await asyncio.wait_for(ack, timeout=_CONFIG_ACK_TIMEOUT_SECONDS)
    except Exception as error:
        await _restore_after_config_send_failure(
            state, previous_config, error, mutation_id
        )
        return
    finally:
        state.config_ack_waiters.pop(mutation_id, None)

    if camera_changed:
        await asyncio.to_thread(_apply_camera)
    toast_success(
        identifier=None,
        content=ToastContent(message_key=success_message_key),
        action=None,
    )
    toast_info(
        identifier=None,
        content=ToastContent(message_key=restart_message_key),
        action=None,
    )


async def _start_connection_change(
    state: RovState,
    previous_config: RovConfig,
    mutation_id: str | None,
    *,
    camera_changed: bool,
    success_message_key: str,
) -> bool:
    """Persist connection settings and confirm the reboot-required contract."""
    restart_message_key = _connection_restart_message_key(
        state.rov_config, previous_config
    )
    if mutation_id is None or not websocket_state.is_client_connected:
        if camera_changed:
            await asyncio.to_thread(_apply_camera)
        toast_success(
            identifier=None,
            content=ToastContent(message_key=success_message_key),
            action=None,
        )
        toast_info(
            identifier=None,
            content=ToastContent(message_key=restart_message_key),
            action=None,
        )
        return True

    ack = asyncio.get_running_loop().create_future()
    state.config_ack_waiters[mutation_id] = ack
    try:
        await send_message_and_wait(_config_message(state, mutation_id))
    except Exception as error:
        state.config_ack_waiters.pop(mutation_id, None)
        await _restore_after_config_send_failure(
            state, previous_config, error, mutation_id
        )
        return False

    task = asyncio.create_task(
        _await_connection_config_ack(
            state,
            previous_config,
            mutation_id,
            ack,
            camera_changed,
            success_message_key,
            restart_message_key,
        )
    )
    state.connection_change_task = task

    def clear_task(completed: asyncio.Task[None]) -> None:
        if state.connection_change_task is completed:
            state.connection_change_task = None

    task.add_done_callback(clear_task)
    return True


def handle_confirm_config(state: RovState, mutation_id: str) -> None:
    """Confirm that the app persisted the connection target for the next boot."""
    waiter = state.config_ack_waiters.get(mutation_id)
    if waiter is not None and not waiter.done():
        waiter.set_result(None)


def _disruptive_config_blocker(
    state: RovState, previous: RovConfig, candidate: RovConfig
) -> str | None:
    changed = (
        previous.mcu_board != candidate.mcu_board
        or previous.thruster_protocol != candidate.thruster_protocol
        or previous.dshot_speed != candidate.dshot_speed
    )
    return disruptive_motor_operation_blocker(state) if changed else None


async def _reject_config_mutation(
    state: RovState, mutation_id: str | None, reason: str
) -> None:
    log_warn(f"Rejected disruptive config mutation because {reason}.")
    await get_message_queue().put(_config_message(state, mutation_id))
    toast_warn(
        identifier=None,
        content=ToastContent(
            message_key="toasts_disruptive_config_blocked",
            description_key="toasts_disruptive_config_blocked_description",
            description_args={"reason": reason},
        ),
        action=None,
    )


def _apply_camera() -> None:
    _run_apply_command(
        "manafish-camera",
        "Applied camera settings and restarted the video stream.",
        "Failed to apply camera settings",
    )


async def handle_set_config(
    state: RovState,
    payload: PartialRovConfig,
    mutation_id: str | None = None,
) -> None:
    """Handle set config message.

    Args:
        state: The ROV state.
        payload: Partial ROV configuration update.
        mutation_id: Identifier echoed in the canonical config response.
    """
    pending = state.connection_change_task
    if pending is not None and not pending.done():
        await _reject_config_mutation(
            state, mutation_id, "another connection change is still being applied"
        )
        return

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
    candidate = RovConfig.model_validate(current_data)
    blocker = _disruptive_config_blocker(state, previous_config, candidate)
    if blocker is not None:
        await _reject_config_mutation(state, mutation_id, blocker)
        return
    state.rov_config = candidate
    state.rov_config.save()
    log_info("Received and applied config update.")
    connection_changed = _connection_changed(state.rov_config, previous_config)
    camera_changed = state.rov_config.camera != previous_camera
    if connection_changed:
        await _start_connection_change(
            state,
            previous_config,
            mutation_id,
            camera_changed=camera_changed,
            success_message_key="toasts_rov_config_set_successfully",
        )
        return

    await get_message_queue().put(_config_message(state, mutation_id))
    if camera_changed:
        await asyncio.to_thread(_apply_camera)

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
    mutation_id: str | None = None,
) -> None:
    """Handle a raw config import without enforcing the current schema.

    Args:
        state: The ROV state.
        payload: Raw config dictionary from the app, possibly from an older or
            newer firmware version.
        mutation_id: Identifier echoed in the canonical config response.
    """
    pending = state.connection_change_task
    if pending is not None and not pending.done():
        await _reject_config_mutation(
            state, mutation_id, "another connection change is still being applied"
        )
        return

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
    blocker = _disruptive_config_blocker(state, previous_config, new_config)
    if blocker is not None:
        await _reject_config_mutation(state, mutation_id, blocker)
        return
    state.rov_config = new_config
    state.rov_config.save()
    log_info(
        f"Imported config from app. Skipped fields: {skipped or 'none'}.",
    )
    connection_changed = _connection_changed(state.rov_config, previous_config)
    camera_changed = state.rov_config.camera != previous_camera
    if connection_changed:
        await _start_connection_change(
            state,
            previous_config,
            mutation_id,
            camera_changed=camera_changed,
            success_message_key="toasts_rov_config_imported",
        )
        return

    await get_message_queue().put(_config_message(state, mutation_id))
    if camera_changed:
        await asyncio.to_thread(_apply_camera)

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
