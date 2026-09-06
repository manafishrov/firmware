import asyncio
import hashlib
import json
import time
from typing import Any, cast

import pytest

from rov_firmware import diagnostics
from rov_firmware.constants import (
    MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE,
    MCU_TELEMETRY_STALE_TIMEOUT_S,
    MCU_TELEMETRY_TYPE_CURRENT,
    MCU_TELEMETRY_TYPE_ERPM,
    MCU_TELEMETRY_TYPE_SIGNAL_QUALITY,
)
from rov_firmware.regulator import Regulator
from rov_firmware.sensors import mcu as mcu_module
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.sensors.pi_power import read_pi_undervoltage
from rov_firmware.serial import SerialManager
from rov_firmware.thrusters import Thrusters
from rov_firmware.websocket.state import websocket_state


@pytest.fixture
def recorder(rov_state, monkeypatch):
    serial = SerialManager(rov_state)
    mcu = McuSensor(rov_state, serial)
    thrusters = Thrusters(rov_state, serial, Regulator(rov_state))
    recorder = diagnostics.FieldDiagnostics(rov_state, serial, mcu, thrusters)
    events = []
    monkeypatch.setattr(
        diagnostics,
        "log_diagnostic",
        lambda event, **fields: events.append((event, fields)),
    )
    monkeypatch.setattr(websocket_state, "is_client_connected", False)
    rov_state.system_health.mcu_healthy = True
    rov_state.system_status.thruster_control_ready = True
    rov_state.system_status.thruster_protocol_state = "ready"
    return recorder, events


def test_summary_rate_and_history_are_bounded(recorder):
    recorder, events = recorder
    for now in range(100, 175):
        recorder.sample(float(now), undervoltage=False)
    assert len(recorder._history) == 60
    assert len([event for event, _ in events if event == "snapshot"]) == 8
    assert not any(event == "fault_history" for event, _ in events)
    # No giant messages that the journal would truncate or the viewer cannot wrap.
    assert max(len(json.dumps(fields)) for _, fields in events) < 16_384


def test_fault_history_is_frozen_and_rate_limited(recorder):
    recorder, events = recorder
    for now in range(100, 160):
        recorder.sample(float(now), undervoltage=False)
    recorder.sample(160.0, undervoltage=True)
    dumped = [fields for event, fields in events if event == "history_sample"]
    assert len(dumped) == 60
    assert dumped[0]["mono_s"] == 101.0
    assert dumped[-1]["pi_undervoltage"] is True
    for now in range(161, 180):
        recorder.sample(float(now), undervoltage=now % 2 == 0)
    assert len([event for event, _ in events if event == "fault_history"]) == 1
    assert dumped[0]["pi_undervoltage"] is False


def test_connect_and_config_changes_repeat_context_without_private_fields(
    recorder, monkeypatch
):
    recorder, events = recorder
    recorder.sample(100.0, undervoltage=False)
    monkeypatch.setattr(websocket_state, "is_client_connected", True)
    recorder.sample(101.0, undervoltage=False)
    recorder.state.rov_config.dshot_speed = 600
    recorder.sample(102.0, undervoltage=False)
    configs = [fields for event, fields in events if event == "configuration"]
    assert len(configs) == 3
    assert configs[-1]["config"]["dshot_speed"] == 600
    assert "ip_address" not in configs[-1]["config"]
    assert "rov_name" not in configs[-1]["config"]
    assert "utc_clock_verified" in configs[-1]


def test_fault_during_cooldown_is_reported_when_cooldown_expires(recorder):
    recorder, events = recorder
    recorder.sample(100.0, undervoltage=True)
    recorder.state.system_status.thruster_protocol_state = "failed"
    recorder.sample(110.0, undervoltage=True)
    assert len([event for event, _ in events if event == "fault_history"]) == 1
    recorder.sample(130.0, undervoltage=True)
    history = [fields for event, fields in events if event == "fault_history"]
    assert history[-1]["reasons"] == {"protocol_failed": 110.0}


def test_unavailable_power_is_not_a_measured_healthy_supply(recorder, tmp_path):
    recorder, events = recorder
    assert read_pi_undervoltage(tmp_path) is None
    recorder.sample(100.0, undervoltage=None)
    snapshot = next(fields for event, fields in events if event == "snapshot")
    assert snapshot["pi_undervoltage"] is None


def test_sampler_uses_capture_time_after_power_probe(recorder, monkeypatch):
    recorder, _ = recorder
    probe_ended = []
    samples = []

    def power_probe():
        time.sleep(0.01)
        probe_ended.append(time.monotonic())
        return False

    def capture(now, **fields):
        samples.append((now, fields))
        raise asyncio.CancelledError

    monkeypatch.setattr(diagnostics, "firmware_manifest", lambda _: [])
    monkeypatch.setattr(diagnostics, "read_pi_undervoltage", power_probe)
    monkeypatch.setattr(recorder, "sample", capture)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(recorder.run())
    assert samples[0][0] >= probe_ended[0]
    assert samples[0][1]["power_probe_s"] >= 0.01
    assert samples[0][1]["scheduler_lag"] >= 0.01


def test_manifest_hashes_only_images_not_keys_or_config(tmp_path):
    image = tmp_path / "mcu-firmware" / "pico-v1.0.3-rc.6.uf2"
    image.parent.mkdir()
    image.write_bytes(b"binary\x00\x0aimage")
    (image.parent / "private.key").write_text("do not read me")
    entries = diagnostics.firmware_manifest(tmp_path)
    assert entries == [
        {
            "file": image.name,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "bytes": image.stat().st_size,
        }
    ]


def test_telemetry_distinguishes_zero_missing_stale_and_short_rpm_dips(
    recorder, monkeypatch
):
    recorder, _ = recorder
    mcu = recorder.mcu
    assert mcu.diagnostic_snapshot(100.0)[0]["erpm"] is None
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: 100.0)
    mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_ERPM, 20)
    mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_ERPM, 0)
    mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_ERPM, 20)
    mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_CURRENT, -5)
    mcu._update_telemetry_item(
        0, MCU_TELEMETRY_TYPE_SIGNAL_QUALITY, MCU_TELEMETRY_SIGNAL_QUALITY_UNAVAILABLE
    )
    row = mcu.diagnostic_snapshot(100.2)[0]
    assert row["erpm"] == 2000
    assert row["erpm_min_since_sample"] == 0
    assert row["erpm_max_since_sample"] == 2000
    assert row["current"] == -5  # Raw wire reading; live safety policy unchanged.
    assert recorder.state.mcu_telemetry.current[0] == 0
    assert row["signal_quality"] is None
    stale_time = 101.0 + MCU_TELEMETRY_STALE_TIMEOUT_S
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: stale_time)
    mcu._expire_stale_telemetry()
    row = mcu.diagnostic_snapshot(stale_time)[0]
    assert row["erpm"] is None
    assert row["last_erpm"] == 2000
    assert row["erpm_stale"] is True
    assert row["erpm_min_since_sample"] is None


def test_ten_second_summary_preserves_mid_window_dips(recorder, monkeypatch):
    recorder, events = recorder
    for now in range(100, 111):
        monkeypatch.setattr(mcu_module.time, "monotonic", lambda now=now: float(now))
        recorder.mcu._update_telemetry_item(
            0, MCU_TELEMETRY_TYPE_ERPM, 0 if now == 105 else 20
        )
        command = 1500 if now == 105 else 1600
        recorder.thrusters._diagnostic_command_min = [command] * 8
        recorder.thrusters._diagnostic_command_max = [command] * 8
        recorder.sample(float(now), undervoltage=False)
    summary = [fields for event, fields in events if event == "snapshot"][-1]
    assert summary["window_sample_count"] == 10
    assert summary["esc"][0]["erpm"] == 2000
    assert summary["esc"][0]["erpm_window_min"] == 0
    assert summary["esc"][0]["erpm_window_max"] == 2000
    assert summary["control"]["usb_command_window_min"] == [1500] * 8
    assert summary["control"]["usb_command_window_max"] == [1600] * 8


def test_new_usb_generation_cannot_reuse_previous_esc_values(recorder, monkeypatch):
    recorder, _ = recorder
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: 100.0)
    recorder.mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_ERPM, 30)
    recorder.serial._connection_generation += 1
    assert recorder.mcu.diagnostic_snapshot(100.1)[0]["erpm"] is None
    recorder.mcu._consume_read_buffer(bytearray(), b"")
    recorder.mcu._update_telemetry_item(0, MCU_TELEMETRY_TYPE_ERPM, 10)
    row = recorder.mcu.diagnostic_snapshot(100.1)[0]
    assert row["erpm"] == 1000
    assert row["erpm_max_since_sample"] == 1000


def test_malformed_usb_capture_is_counted_bounded_and_rate_limited(
    recorder, monkeypatch
):
    recorder, events = recorder
    monkeypatch.setattr(
        mcu_module,
        "log_diagnostic",
        lambda event, **fields: events.append((event, fields)),
    )
    monkeypatch.setattr(mcu_module.time, "monotonic", lambda: 100.0)
    for _ in range(1000):
        recorder.mcu._record_invalid_packet(bytes(range(100)))
    assert recorder.mcu.invalid_usb_packets == 1000
    assert len(events) == 1
    assert len(events[0][1]["first_32_bytes_hex"]) == 64


def test_command_observation_does_not_modify_wire_packet(recorder):
    recorder, _ = recorder

    class Writer:
        def __init__(self):
            self.writes = []

        def write(self, packet):
            self.writes.append(bytes(packet))

        async def drain(self):
            pass

    writer = Writer()
    values = [1500] * 8
    asyncio.run(recorder.thrusters._send_packet(cast(Any, writer), values))
    values[0] = 1900
    snapshot = recorder.thrusters.diagnostic_snapshot(200.0)
    assert snapshot["last_usb_command"] == [1500] * 8
    assert len(writer.writes) == 1
    assert len(writer.writes[0]) == 18
    assert snapshot["write_failures"] == 0
