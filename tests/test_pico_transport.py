"""Wire compatibility, actual-apply barriers and stale authority regression tests."""

import asyncio
import struct
import time
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from rov_firmware import pico_protocol as wire
from rov_firmware.models.config import PartialRovConfig, RovConfig
from rov_firmware.models.sensors import PressureData
from rov_firmware.pico_control import PicoControl
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.serial import SerialManager
from rov_firmware.websocket.receive import config as config_handler
from rov_firmware.websocket.state import websocket_state


@pytest.fixture
def endpoint(rov_state):
    serial = SerialManager(rov_state)
    control = PicoControl(rov_state, serial)
    control._reset_connection()
    rov_state.pico = control
    return control


def ack(request, result=wire.APPLIED, generation=0, digest=0):
    return wire.Frame(
        wire.ACK,
        request.session,
        request.sequence,
        struct.pack("<BBHII", request.kind, result, 0, generation, digest),
    )


def test_crc32c_standard_check_and_frame_roundtrip():
    assert wire.crc32c(b"123456789") == 0xE3069283
    packet = wire.Frame(wire.CONTROL, 123, 45, bytes([0x5A, 0xE7, 0xE8]) * 20).encode()
    assert wire.decode(packet).payload == bytes([0x5A, 0xE7, 0xE8]) * 20
    corrupt = bytearray(packet)
    corrupt[20] ^= 1
    with pytest.raises(ValueError):
        wire.decode(bytes(corrupt))


def test_settings_image_contains_protocol_and_every_calibration_field():
    config = RovConfig()
    config.nullspace_vectors = [np.arange(8, dtype=np.float32)]
    image = wire.settings_image(config)
    assert len(image) == 628
    assert struct.unpack_from("<HH", image, 624) == (1, 300)
    assert struct.unpack_from("<4f", image) == (6, 2, pytest.approx(0.6), 120)
    assert struct.unpack_from("<I", image, 364) == (1,)
    assert struct.unpack_from("<8f", image, 368) == tuple(range(8))
    assert image[400:624] == bytes(224)
    config.nullspace_vectors *= 9
    with pytest.raises(ValueError, match="at most 8"):
        wire.settings_image(config)


def test_capability_gate_never_sends_extended_bytes_to_old_device(
    endpoint, monkeypatch
):
    packets = []

    async def write(packet):
        packets.append(packet)

    monkeypatch.setattr(endpoint, "_write", write)
    monkeypatch.setattr("rov_firmware.pico_control.REQUEST_RETRY", 0.001)

    async def run():
        with pytest.raises(RuntimeError, match="capability unavailable"):
            await endpoint._negotiate()

    asyncio.run(run())
    assert all(packet[0] in (0x5A, 0xC5) for packet in packets)
    assert all(len(packet) in (7, 18) for packet in packets)
    assert endpoint.session == 0
    assert not endpoint._ready


def test_reliable_request_retries_identical_sequence_no_wrong_ack(
    endpoint, monkeypatch
):
    endpoint.session = 42
    frames = []

    async def write(packet):
        frame = wire.decode(packet)
        frames.append(frame)
        if len(frames) == 1:
            endpoint.receive(
                wire.Frame(wire.ACK, 43, frame.sequence, ack(frame).payload)
            )
        else:
            endpoint.receive(ack(frame))

    monkeypatch.setattr(endpoint, "_write", write)
    monkeypatch.setattr("rov_firmware.pico_control.REQUEST_RETRY", 0.001)
    asyncio.run(endpoint._request(wire.SET_DEPTH, struct.pack("<f", 3)))
    assert len(frames) == 2
    assert frames[0] == frames[1]


def test_atomic_settings_commit_checks_digest(endpoint, monkeypatch):
    endpoint.session = 123
    endpoint._negotiated = True
    frames = []
    generation = digest = 0

    async def write(packet):
        nonlocal generation, digest
        frame = wire.decode(packet)
        frames.append(frame)
        if frame.kind == wire.BEGIN:
            generation, _, digest = struct.unpack("<III", frame.payload)
        if frame.kind in (wire.BEGIN, wire.CHUNK):
            endpoint.receive(ack(frame, wire.STAGED))
        elif frame.kind == wire.COMMIT:
            endpoint.receive(ack(frame, generation=generation, digest=digest))
        elif frame.kind in (wire.ABORT, wire.QUERY):
            endpoint.receive(ack(frame))

    monkeypatch.setattr(endpoint, "_write", write)
    asyncio.run(endpoint.apply_config(endpoint.state.rov_config))
    assert [frame.kind for frame in frames] == [
        wire.RAW_MOTORS,
        wire.ABORT,
        wire.QUERY,
        wire.BEGIN,
        wire.CHUNK,
        wire.COMMIT,
    ]
    assert len(frames[4].payload) == 632
    assert not endpoint._ready  # Persistence is a separate mandatory barrier.
    endpoint.confirm_persisted_config()
    assert endpoint._ready


def test_stale_app_input_is_invalid_despite_live_usb(endpoint, monkeypatch):
    endpoint.session = 1
    endpoint.state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
    endpoint.state.thrusters.last_direction_time = time.time() - 1
    write = AsyncMock()
    monkeypatch.setattr(endpoint, "_write", write)
    asyncio.run(endpoint._send_direction(time.monotonic()))
    values = struct.unpack("<9fI", wire.decode(write.call_args.args[0]).payload)
    assert not values[-1] & 4
    assert values[:8] == (0,) * 8


def test_same_value_fresh_pressure_sample_still_renews_pressure_only(
    endpoint, monkeypatch
):
    endpoint.session = 1
    endpoint.state.system_health.pressure_sensor_healthy = True
    write = AsyncMock()
    monkeypatch.setattr(endpoint, "_write", write)

    async def run():
        endpoint.state.pressure = PressureData(depth=1, sample_time=time.monotonic())
        await endpoint._send_pressure()
        await endpoint._send_pressure()
        endpoint.state.pressure = PressureData(depth=1, sample_time=time.monotonic())
        await endpoint._send_pressure()

    asyncio.run(run())
    assert write.await_count == 2
    assert all(
        wire.decode(call.args[0]).kind == wire.PRESSURE for call in write.call_args_list
    )


def test_extended_parser_does_not_dispatch_embedded_legacy_packets(
    endpoint, monkeypatch
):
    sensor = McuSensor(endpoint.state, endpoint.serial)
    handler = Mock()
    monkeypatch.setattr(sensor, "_handle_esc_firmware_recovery_required", handler)
    payload = bytes([0xE9, 9]) + bytes(10)
    frame = wire.Frame(0xFF, 0, 0, payload).encode()
    buffer = bytearray()
    for byte in frame:
        sensor._consume_read_buffer(buffer, bytes([byte]))
    handler.assert_not_called()
    assert not buffer


def test_config_ack_precedes_persistence_canonical_and_confirmed_success(
    rov_state, monkeypatch
):
    events = []

    class FakePico:
        async def apply_config(self, _candidate):
            events.append("applied")
            assert rov_state.rov_config.regulator.pitch.kp == 6

        def confirm_persisted_config(self):
            events.append("resume")

    rov_state.pico = FakePico()
    monkeypatch.setattr(RovConfig, "save", lambda _self: events.append("persisted"))
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handler, "get_message_queue", lambda: queue)
    monkeypatch.setattr(
        config_handler, "toast_success", lambda **_kwargs: events.append("success")
    )
    monkeypatch.setattr(websocket_state, "is_client_connected", True)

    async def run():
        regulator = rov_state.rov_config.regulator.model_copy(deep=True)
        regulator.pitch.kp = 7
        await config_handler.handle_set_config(
            rov_state, PartialRovConfig(regulator=regulator), "test"
        )
        assert events == ["applied", "persisted", "resume"]
        response = await queue.get()
        assert response.payload.config.regulator.pitch.kp == 7
        assert "error" not in response.payload.model_dump()
        config_handler.handle_confirm_config(rov_state, "test")
        # No scheduling gap: the app can immediately send its next queued mutation.
        await config_handler.handle_set_config(
            rov_state, PartialRovConfig(rov_name="next"), "next"
        )
        second = await queue.get()
        assert second.payload.error is None
        assert second.payload.config.rov_name == "next"
        config_handler.handle_confirm_config(rov_state, "next")
        await asyncio.gather(*rov_state.config_confirmation_tasks)
        assert events[-1] == "success"

    asyncio.run(run())


def test_config_rejection_or_persistence_failure_has_error_no_success(
    rov_state, monkeypatch
):
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handler, "get_message_queue", lambda: queue)
    success = Mock()
    monkeypatch.setattr(config_handler, "toast_success", success)
    monkeypatch.setattr(config_handler, "toast_warn", Mock())
    save = Mock()
    monkeypatch.setattr(RovConfig, "save", save)

    async def run():
        await config_handler.handle_set_config(
            rov_state, PartialRovConfig(dshot_speed=600), "failed"
        )
        response = await queue.get()
        assert response.payload.error
        assert response.payload.mutation_id == "failed"
        assert response.payload.config.dshot_speed == 300

    asyncio.run(run())
    save.assert_not_called()
    success.assert_not_called()


def test_maintenance_gate_holds_local_latch_until_explicit_exit(endpoint, monkeypatch):
    endpoint.session = 7
    endpoint._ready = endpoint._negotiated = True
    sent = []

    async def write(packet):
        frame = wire.decode(packet)
        sent.append(frame)
        if frame.kind == 0x25:
            endpoint.receive(ack(frame))

    monkeypatch.setattr(endpoint, "_write", write)

    async def run():
        await endpoint.enter_maintenance()
        assert endpoint._maintenance
        assert not endpoint._ready
        assert endpoint.session == 0
        with pytest.raises(RuntimeError, match="maintenance"):
            await endpoint.apply_config(endpoint.state.rov_config)
        endpoint.leave_maintenance()
        assert not endpoint._maintenance
        assert not endpoint._negotiated

    asyncio.run(run())
    assert [frame.kind for frame in sent] == [wire.RAW_MOTORS, 0x25]


def test_development_override_requires_explicit_env_and_verified_identity(
    endpoint, monkeypatch
):
    monkeypatch.setenv("MANAFISH_PICO_CONTROL_DEVELOPMENT", "1")
    assert not endpoint.suppress_bundled_reconciliation
    endpoint.development_identity = "pico-control-dev:test"
    assert endpoint.suppress_bundled_reconciliation
    monkeypatch.delenv("MANAFISH_PICO_CONTROL_DEVELOPMENT")
    assert not endpoint.suppress_bundled_reconciliation


def test_attitude_and_raw_imu_project_without_pi_controller_execution(endpoint):
    endpoint.session = 3
    endpoint._settings_generation = 2
    endpoint._ready = True
    raw = struct.pack("<7f", 1, 2, -9.81, 0.1, 0.2, 0.3, 24)
    endpoint.receive(wire.Frame(wire.IMU, 3, 4, raw))
    payload = struct.pack(
        "<Q9f5I8HI",
        1000,
        0,
        0,
        0,
        1,
        0,
        0,
        2**-0.5,
        2**-0.5,
        2.5,
        2,
        15,
        7,
        100,
        100,
        *([1000] * 8),
        42,
    )
    assert len(payload) == 84
    endpoint.receive(wire.Frame(wire.ATTITUDE, 3, 5, payload))
    assert endpoint.state.regulator.desired_yaw == pytest.approx(90)
    assert endpoint.state.regulator.desired_depth == 2.5
    assert endpoint.state.thrusters.work_indicator_percentage == 42
    assert endpoint.state.system_health.imu_healthy
    assert endpoint.state.imu.temperature == 24
    received = endpoint._last_raw_imu
    endpoint.receive(wire.Frame(wire.IMU, 3, 4, raw))
    assert (
        endpoint._last_raw_imu == received
    )  # Duplicate telemetry cannot renew freshness.
    endpoint._expire_health(time.monotonic() + 1)
    assert not endpoint.state.system_health.imu_healthy
    assert not endpoint.state.system_status.thruster_control_ready


def test_old_pressure_is_not_relabelled_fresh_after_reconnect(endpoint, monkeypatch):
    endpoint.session = 1
    endpoint.state.system_health.pressure_sensor_healthy = True
    endpoint.state.pressure = PressureData(depth=1, sample_time=time.monotonic() - 2)
    write = AsyncMock()
    monkeypatch.setattr(endpoint, "_write", write)
    asyncio.run(endpoint._send_pressure())
    payload = wire.decode(write.call_args.args[0]).payload
    assert struct.unpack("<ffI", payload)[2] == 0


def test_invalid_schema_rejection_preserves_mutation_correlation(
    rov_state, monkeypatch
):
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handler, "get_message_queue", lambda: queue)
    warning = Mock()
    monkeypatch.setattr(config_handler, "toast_warn", warning)

    async def run():
        await config_handler.reject_invalid_config_message(
            rov_state,
            {
                "type": "setConfig",
                "payload": {"mutationId": "bad-schema", "config": {"dshotSpeed": 9}},
            },
            "invalid DShot rate",
        )
        response = await queue.get()
        assert response.payload.mutation_id == "bad-schema"
        assert response.payload.error == "invalid DShot rate"

    asyncio.run(run())
    warning.assert_called_once()
