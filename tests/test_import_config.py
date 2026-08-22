import asyncio
from pathlib import Path

import pytest

from rov_firmware.models.config import McuBoard, RovConfig
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
    rov_state.device_info.mcu_firmware_version = "real-mcu-version"
    rov_state.device_info.esc_firmware_versions = ["2.20.0"] * 8

    payload = _baseline_export(rov_state)
    payload["firmwareVersion"] = "spoofed"
    payload["mcuFirmwareVersion"] = "spoofed"
    payload["escFirmwareVersions"] = ["spoofed"] * 8
    payload["rovName"] = "X"

    asyncio.run(handle_import_config(rov_state, payload))

    assert rov_state.rov_config.firmware_version != "spoofed"
    assert rov_state.device_info.mcu_firmware_version == "real-mcu-version"
    assert rov_state.device_info.esc_firmware_versions == ["2.20.0"] * 8
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


def test_partial_old_import_uses_current_pico2_for_dshot_1200_migration(rov_state):
    rov_state.rov_config.mcu_board = McuBoard.PICO2

    asyncio.run(
        handle_import_config(
            rov_state,
            {"firmwareVersion": "1.1.5", "dshotSpeed": 1200},
        )
    )

    assert rov_state.rov_config.mcu_board is McuBoard.PICO2
    assert rov_state.rov_config.dshot_speed == 1200


def test_import_with_malformed_version_still_applies_migrations(rov_state):
    asyncio.run(
        handle_import_config(
            rov_state,
            {
                "firmwareVersion": None,
                "power": {"internalResistance": 0.1},
                "rovName": "Migrated",
            },
        )
    )

    assert rov_state.rov_config.rov_name == "Migrated"


def test_import_merges_partial_camera_with_current_values(rov_state, monkeypatch):
    rov_state.rov_config.camera.width = 1280
    rov_state.rov_config.camera.bitrate = 8_000_000
    monkeypatch.setattr(config_handlers, "_apply_camera", lambda: None)

    asyncio.run(handle_import_config(rov_state, {"camera": {"framerate": 24}}))

    assert rov_state.rov_config.camera.framerate == 24
    assert rov_state.rov_config.camera.width == 1280
    assert rov_state.rov_config.camera.bitrate == 8_000_000


def test_import_persists_to_disk(rov_state, isolated_config_path):
    payload = _baseline_export(rov_state)
    payload["rovName"] = "Persisted"

    asyncio.run(handle_import_config(rov_state, payload))

    assert isolated_config_path.exists()
    assert "Persisted" in isolated_config_path.read_text()


def test_import_publishes_canonical_config_to_client(rov_state, monkeypatch):
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handlers, "get_message_queue", lambda: queue)

    asyncio.run(handle_import_config(rov_state, {"rovName": "Published"}))

    message = queue.get_nowait()
    assert message.payload.config.rov_name == "Published"


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


def test_import_uses_network_restart_when_ip_and_port_changed(rov_state, monkeypatch):
    network_calls: list[str] = []
    restart_calls: list[None] = []

    async def restart_firmware() -> bool:
        restart_calls.append(None)
        return True

    def apply_ip_address(ip_address: str) -> bool:
        network_calls.append(ip_address)
        return True

    monkeypatch.setattr(config_handlers, "_apply_ip_address", apply_ip_address)
    monkeypatch.setattr(config_handlers, "_restart_firmware", restart_firmware)

    payload = _baseline_export(rov_state)
    payload.update({"ipAddress": "10.10.11.10", "websocketPort": 9100})
    asyncio.run(handle_import_config(rov_state, payload))

    assert network_calls == ["10.10.11.10"]
    assert restart_calls == []


def test_import_confirms_correlated_config_before_connection_apply(
    rov_state, monkeypatch
):
    events: list[str] = []

    async def send_config(message):
        assert message.payload.mutation_id == "import-1"
        events.append("confirm")

    async def apply_connection(_state, _previous):
        events.append("apply")
        return True

    monkeypatch.setattr(config_handlers.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(config_handlers, "send_message_and_wait", send_config)
    monkeypatch.setattr(config_handlers, "_apply_connection_change", apply_connection)

    asyncio.run(
        handle_import_config(
            rov_state,
            {"ipAddress": "10.10.11.10"},
            mutation_id="import-1",
        )
    )

    assert events == ["confirm", "apply"]


def test_import_restores_config_when_confirmation_times_out(rov_state, monkeypatch):
    apply_calls: list[None] = []

    async def timeout(_message):
        raise TimeoutError

    async def apply_connection(_state, _previous):
        apply_calls.append(None)
        return True

    monkeypatch.setattr(config_handlers.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(config_handlers, "send_message_and_wait", timeout)
    monkeypatch.setattr(config_handlers, "_apply_connection_change", apply_connection)

    asyncio.run(
        handle_import_config(
            rov_state,
            {"ipAddress": "10.10.11.10"},
            mutation_id="import-2",
        )
    )

    assert apply_calls == []
    assert rov_state.rov_config.ip_address == "10.10.10.10"
    assert RovConfig.load().ip_address == "10.10.10.10"
