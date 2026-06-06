import asyncio
from pathlib import Path

import numpy as np
import pytest

from rov_firmware.models.config import PartialRovConfig, RovConfig
from rov_firmware.websocket.receive.config import handle_set_config


@pytest.fixture(autouse=True)
def isolated_config_path(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(RovConfig, "_config_path", config_path)
    return config_path


def test_set_config_removes_last_nullspace_vector(rov_state):
    rov_state.rov_config.nullspace_vectors = [np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)]

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


def test_set_config_persists_empty_nullspace_vectors_to_disk(rov_state, isolated_config_path):
    rov_state.rov_config.nullspace_vectors = [np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)]

    payload = PartialRovConfig.model_validate({"nullspaceVectors": []})
    asyncio.run(handle_set_config(rov_state, payload))

    saved = RovConfig.load()
    assert saved.nullspace_vectors == []


def test_set_config_does_not_modify_fields_not_in_payload(rov_state):
    rov_state.rov_config.rov_name = "TestROV"
    rov_state.rov_config.nullspace_vectors = [np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)]

    payload = PartialRovConfig.model_validate({"nullspaceVectors": []})
    asyncio.run(handle_set_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "TestROV"
    assert rov_state.rov_config.nullspace_vectors == []
