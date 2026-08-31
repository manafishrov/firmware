import asyncio
from pathlib import Path
import subprocess

import numpy as np
import pytest

from rov_firmware.models.config import PartialRovConfig, RovConfig, ThrusterProtocol
from rov_firmware.models.system import EscFirmwareUpdateStage
from rov_firmware.websocket.receive import config as config_handlers
from rov_firmware.websocket.receive.config import handle_set_config


@pytest.fixture(autouse=True)
def isolated_config_path(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(RovConfig, "_config_path", config_path)
    return config_path


def test_set_config_removes_last_nullspace_vector(rov_state):
    rov_state.rov_config.nullspace_vectors = [
        np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    ]

    payload = PartialRovConfig.model_validate({"nullspaceVectors": []})
    asyncio.run(handle_set_config(rov_state, payload))

    assert rov_state.rov_config.nullspace_vectors == []


def test_protocol_change_is_blocked_while_auto_stabilization_is_active(rov_state):
    previous = rov_state.rov_config.model_copy(deep=True)
    candidate = previous.model_copy(update={"thruster_protocol": ThrusterProtocol.PWM})
    rov_state.system_status.auto_stabilization = True

    assert (
        config_handlers._disruptive_config_blocker(rov_state, previous, candidate)
        == "auto-stabilization is active"
    )


def test_protocol_change_is_blocked_during_esc_version_confirmation(rov_state):
    previous = rov_state.rov_config.model_copy(deep=True)
    candidate = previous.model_copy(update={"thruster_protocol": ThrusterProtocol.PWM})
    rov_state.esc_firmware_update.stage = EscFirmwareUpdateStage.AWAITING_TELEMETRY

    assert (
        config_handlers._disruptive_config_blocker(rov_state, previous, candidate)
        == "ESC firmware version confirmation is still running"
    )


def test_set_config_removes_one_of_two_nullspace_vectors(rov_state):
    rov_state.rov_config.nullspace_vectors = [
        np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
        np.array([0, 1, 0, 0, 0, 0, 0, 0], dtype=np.float32),
    ]

    payload = PartialRovConfig.model_validate(
        {"nullspaceVectors": [[1, 0, 0, 0, 0, 0, 0, 0]]}
    )
    asyncio.run(handle_set_config(rov_state, payload))

    assert len(rov_state.rov_config.nullspace_vectors) == 1
    assert np.array_equal(
        rov_state.rov_config.nullspace_vectors[0],
        np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
    )


def test_set_config_persists_empty_nullspace_vectors_to_disk(rov_state):
    rov_state.rov_config.nullspace_vectors = [
        np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    ]

    payload = PartialRovConfig.model_validate({"nullspaceVectors": []})
    asyncio.run(handle_set_config(rov_state, payload))

    saved = RovConfig.load()
    assert saved.nullspace_vectors == []


def test_set_config_does_not_modify_fields_not_in_payload(rov_state):
    rov_state.rov_config.rov_name = "TestROV"
    rov_state.rov_config.nullspace_vectors = [
        np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    ]

    payload = PartialRovConfig.model_validate({"nullspaceVectors": []})
    asyncio.run(handle_set_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "TestROV"
    assert rov_state.rov_config.nullspace_vectors == []


def test_set_config_applies_camera_only_when_camera_changed(rov_state, monkeypatch):
    apply_calls: list[None] = []
    monkeypatch.setattr(
        config_handlers, "_apply_camera", lambda: apply_calls.append(None)
    )

    unrelated_payload = PartialRovConfig.model_validate({"rovName": "Updated"})
    asyncio.run(handle_set_config(rov_state, unrelated_payload))
    assert apply_calls == []

    camera_payload = PartialRovConfig.model_validate({"camera": {"framerate": 24}})
    asyncio.run(handle_set_config(rov_state, camera_payload))
    assert apply_calls == [None]


def test_set_config_preserves_unspecified_camera_fields(rov_state, monkeypatch):
    rov_state.rov_config.camera.width = 1280
    rov_state.rov_config.camera.bitrate = 8_000_000
    monkeypatch.setattr(config_handlers, "_apply_camera", lambda: None)

    payload = PartialRovConfig.model_validate({"camera": {"framerate": 24}})
    asyncio.run(handle_set_config(rov_state, payload))

    assert rov_state.rov_config.camera.framerate == 24
    assert rov_state.rov_config.camera.width == 1280
    assert rov_state.rov_config.camera.bitrate == 8_000_000


def test_apply_command_has_a_timeout(monkeypatch):
    calls: list[dict] = []
    warnings: list[str] = []
    monkeypatch.setattr(
        config_handlers.shutil, "which", lambda binary: f"/bin/{binary}"
    )

    def run(*args, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(config_handlers.subprocess, "run", run)
    monkeypatch.setattr(config_handlers, "log_warn", warnings.append)

    config_handlers._apply_camera()

    assert calls == [
        {
            "check": True,
            "capture_output": True,
            "timeout": config_handlers._APPLY_COMMAND_TIMEOUT_SECONDS,
        }
    ]
    assert warnings and warnings[0].startswith("Failed to apply camera settings:")


def test_connection_settings_are_persisted_without_live_network_mutation(
    rov_state, monkeypatch
):
    info_keys: list[str] = []
    monkeypatch.setattr(
        config_handlers,
        "toast_info",
        lambda *, content, **_kwargs: info_keys.append(content.message_key),
    )

    payload = PartialRovConfig.model_validate(
        {"ipAddress": "10.10.11.10", "websocketPort": 9100}
    )
    asyncio.run(handle_set_config(rov_state, payload))

    persisted = RovConfig.load()
    assert persisted.ip_address == "10.10.11.10"
    assert persisted.websocket_port == 9100
    assert info_keys == ["toasts_rov_connection_restart_required"]


def test_connection_change_waits_for_app_ack_before_announcing_reboot(
    rov_state, monkeypatch
):
    events: list[str] = []

    async def send_config(message):
        assert message.payload.mutation_id == "set-1"
        events.append("config")

    monkeypatch.setattr(config_handlers.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(config_handlers, "send_message_and_wait", send_config)
    monkeypatch.setattr(
        config_handlers,
        "toast_info",
        lambda **_kwargs: events.append("restart-required"),
    )

    async def run_test():
        payload = PartialRovConfig.model_validate({"ipAddress": "10.10.11.10"})
        await handle_set_config(rov_state, payload, mutation_id="set-1")
        assert events == ["config"]
        config_handlers.handle_confirm_config(rov_state, "set-1")
        assert rov_state.connection_change_task is not None
        await rov_state.connection_change_task

    asyncio.run(run_test())

    assert events == ["config", "restart-required"]


def test_set_config_restores_config_when_confirmation_times_out(rov_state, monkeypatch):
    async def timeout(_message):
        raise TimeoutError

    monkeypatch.setattr(config_handlers.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(config_handlers, "send_message_and_wait", timeout)

    payload = PartialRovConfig.model_validate({"ipAddress": "10.10.11.10"})
    asyncio.run(handle_set_config(rov_state, payload, mutation_id="set-2"))

    assert rov_state.rov_config.ip_address == "10.10.10.10"
    assert RovConfig.load().ip_address == "10.10.10.10"


def test_set_config_waits_for_application_ack_before_reboot_notice(
    rov_state, monkeypatch
):
    info_calls: list[None] = []

    async def send_config(_message):
        return None

    monkeypatch.setattr(config_handlers.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(config_handlers, "send_message_and_wait", send_config)
    monkeypatch.setattr(
        config_handlers, "toast_info", lambda **_kwargs: info_calls.append(None)
    )
    monkeypatch.setattr(config_handlers, "_CONFIG_ACK_TIMEOUT_SECONDS", 0)

    async def run_test():
        payload = PartialRovConfig.model_validate({"ipAddress": "10.10.11.10"})
        await handle_set_config(rov_state, payload, mutation_id="set-ack-timeout")
        assert rov_state.connection_change_task is not None
        await rov_state.connection_change_task

    asyncio.run(run_test())

    assert info_calls == []
    assert rov_state.rov_config.ip_address == "10.10.10.10"
