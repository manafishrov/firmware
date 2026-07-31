import asyncio
from pathlib import Path

import numpy as np
import pytest

from rov_firmware.models.config import PartialRovConfig, RovConfig
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


def test_set_config_restarts_firmware_when_websocket_port_changed(
    rov_state, monkeypatch
):
    restart_calls: list[None] = []

    async def restart_firmware() -> bool:
        restart_calls.append(None)
        return True

    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)

    payload = PartialRovConfig.model_validate({"websocketPort": 9100})
    asyncio.run(handle_set_config(rov_state, payload))

    assert restart_calls == [None]


def test_set_config_applies_network_once_when_ip_and_port_changed(
    rov_state, monkeypatch
):
    network_calls: list[str] = []
    restart_calls: list[None] = []
    monkeypatch.setattr(
        config_handlers,
        "_apply_ip_address",
        network_calls.append,
    )

    async def restart_firmware() -> bool:
        restart_calls.append(None)
        return True

    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)

    payload = PartialRovConfig.model_validate(
        {"ipAddress": "10.10.11.10", "websocketPort": 9100}
    )
    asyncio.run(handle_set_config(rov_state, payload))

    assert network_calls == ["10.10.11.10"]
    assert restart_calls == []


def test_set_config_reports_restart_failure_without_success(rov_state, monkeypatch):
    success_calls: list[None] = []
    warning_keys: list[str] = []

    async def restart_firmware() -> bool:
        return False

    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)
    monkeypatch.setattr(
        config_handlers,
        "toast_success",
        lambda **_kwargs: success_calls.append(None),
    )
    monkeypatch.setattr(
        config_handlers,
        "toast_warn",
        lambda *, content, **_kwargs: warning_keys.append(content.message_key),
    )

    payload = PartialRovConfig.model_validate({"websocketPort": 9100})
    asyncio.run(handle_set_config(rov_state, payload))

    assert success_calls == []
    assert warning_keys == ["toasts_rov_connection_restart_failed"]
