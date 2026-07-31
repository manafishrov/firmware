import asyncio
from pathlib import Path

import pytest

from rov_firmware.models.config import RovConfig
from rov_firmware.websocket.receive import config as config_handlers
from rov_firmware.websocket.receive.config import handle_import_config


@pytest.fixture(autouse=True)
def isolated_config_path(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(RovConfig, "_config_path", config_path)
    return config_path


def _baseline_export(rov_state) -> dict:
    return rov_state.rov_config.model_dump(by_alias=True)


def test_import_full_baseline_export_applies_cleanly(rov_state):
    payload = _baseline_export(rov_state)
    payload["rovName"] = "Imported"
    payload["smoothingFactor"] = 0.42

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "Imported"
    assert rov_state.rov_config.smoothing_factor == pytest.approx(0.42)


def test_import_preserves_device_reported_fields(rov_state):
    rov_state.rov_config.mcu_firmware_version = "real-mcu-version"

    payload = _baseline_export(rov_state)
    payload["firmwareVersion"] = "spoofed"
    payload["mcuFirmwareVersion"] = "spoofed"
    payload["rovName"] = "X"

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.firmware_version != "spoofed"
    assert rov_state.rov_config.mcu_firmware_version == "real-mcu-version"
    assert rov_state.rov_config.rov_name == "X"


def test_import_ignores_unknown_fields_from_newer_firmware(rov_state):
    payload = _baseline_export(rov_state)
    payload["rovName"] = "FromFutureFirmware"
    payload["someUnknownNewField"] = {"foo": "bar"}
    payload["anotherFutureField"] = 42

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "FromFutureFirmware"


def test_import_falls_back_to_tolerant_merge_when_validation_fails(rov_state):
    payload = _baseline_export(rov_state)
    payload["rovName"] = "PartialImport"
    payload["dshotSpeed"] = 99999

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "PartialImport"
    assert rov_state.rov_config.dshot_speed == 300


def test_import_keeps_current_values_for_fields_not_in_payload(rov_state):
    rov_state.rov_config.smoothing_factor = 0.7

    payload = {"rovName": "MinimalImport"}

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.rov_name == "MinimalImport"
    assert rov_state.rov_config.smoothing_factor == pytest.approx(0.7)


def test_import_persists_to_disk(rov_state, isolated_config_path):
    payload = _baseline_export(rov_state)
    payload["rovName"] = "Persisted"

    asyncio.run(handle_import_config(rov_state, payload))

    assert isolated_config_path.exists()
    assert "Persisted" in isolated_config_path.read_text()


def test_import_restarts_firmware_when_websocket_port_changed(rov_state, monkeypatch):
    restart_calls: list[None] = []

    async def restart_firmware() -> bool:
        restart_calls.append(None)
        return True

    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)

    payload = _baseline_export(rov_state)
    payload["websocketPort"] = 9100
    asyncio.run(handle_import_config(rov_state, payload))

    assert restart_calls == [None]


def test_import_applies_network_once_when_ip_and_port_changed(rov_state, monkeypatch):
    network_calls: list[str] = []
    restart_calls: list[None] = []

    async def restart_firmware() -> bool:
        restart_calls.append(None)
        return True

    monkeypatch.setattr(config_handlers, "_apply_ip_address", network_calls.append)
    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)

    payload = _baseline_export(rov_state)
    payload.update({"ipAddress": "10.10.11.10", "websocketPort": 9100})
    asyncio.run(handle_import_config(rov_state, payload))

    assert network_calls == ["10.10.11.10"]
    assert restart_calls == []
