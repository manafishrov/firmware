"""Failure-injection tests for confirmed settings and maintenance authority."""

import asyncio
import struct
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from rov_firmware import pico_protocol as wire
from rov_firmware.models.config import PartialRovConfig, RovConfig
from rov_firmware.pico_control import PicoControl
from rov_firmware.serial import SerialManager
from rov_firmware.websocket.receive import (
    config as config_handler,
    regulator as regulator_handler,
)
from rov_firmware.websocket.state import websocket_state


def reply(frame, result=0, generation=0, digest=0):
    return wire.Frame(
        wire.ACK,
        frame.session,
        frame.sequence,
        struct.pack("<BBHII", frame.kind, result, 0, generation, digest),
    )


@pytest.fixture
def endpoint(rov_state):
    control = PicoControl(rov_state, SerialManager(rov_state))
    control._reset_connection()
    control.session = 123
    control._negotiated = True
    rov_state.pico = control
    return control


def test_lost_commit_ack_is_recovered_only_by_matching_query(endpoint, monkeypatch):
    active_generation = active_digest = 0
    commit_frames = []
    queries = []

    async def write(packet):
        nonlocal active_generation, active_digest
        frame = wire.decode(packet)
        if frame.kind == wire.RAW_MOTORS:
            return
        if frame.kind == wire.COMMIT:
            active_generation, active_digest = struct.unpack("<II", frame.payload)
            commit_frames.append(frame)
            return  # The image applied, but every commit ACK was lost.
        if frame.kind == wire.QUERY:
            queries.append(frame)
        endpoint.receive(
            reply(
                frame,
                wire.STAGED if frame.kind in (wire.BEGIN, wire.CHUNK) else wire.APPLIED,
                active_generation,
                active_digest,
            )
        )

    monkeypatch.setattr(endpoint, "_write", write)
    monkeypatch.setattr("rov_firmware.pico_control.REQUEST_RETRY", 0.001)
    asyncio.run(endpoint.apply_config(endpoint.state.rov_config))
    assert len(commit_frames) == 14
    assert all(frame == commit_frames[0] for frame in commit_frames)
    assert len(queries) == 2
    assert endpoint._settings_crc == active_digest
    assert not endpoint._ready  # Still waiting for host persistence.


def test_wrong_applied_digest_inhibits_output(endpoint, monkeypatch):
    async def write(packet):
        frame = wire.decode(packet)
        if frame.kind == wire.RAW_MOTORS:
            return
        endpoint.receive(
            reply(
                frame,
                wire.STAGED if frame.kind in (wire.BEGIN, wire.CHUNK) else wire.APPLIED,
            )
        )

    monkeypatch.setattr(endpoint, "_write", write)

    async def run():
        with pytest.raises(RuntimeError, match="different settings image"):
            await endpoint.apply_config(endpoint.state.rov_config)

    asyncio.run(run())
    assert not endpoint._ready
    assert not endpoint.state.system_status.thruster_control_ready


def test_persistence_failure_after_apply_never_resumes_or_publishes_candidate(
    endpoint, monkeypatch
):
    endpoint._ready = False
    monkeypatch.setattr(endpoint, "apply_config", AsyncMock())
    resume = Mock()
    monkeypatch.setattr(endpoint, "confirm_persisted_config", resume)

    def fail_save(_self):
        msg = "injected disk failure"
        raise OSError(msg)

    monkeypatch.setattr(RovConfig, "save", fail_save)
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handler, "get_message_queue", lambda: queue)
    success = Mock()
    monkeypatch.setattr(config_handler, "toast_success", success)
    monkeypatch.setattr(config_handler, "toast_warn", Mock())

    async def run():
        await config_handler.handle_set_config(
            endpoint.state, PartialRovConfig(dshot_speed=600), "disk"
        )
        response = await queue.get()
        assert response.payload.error == "injected disk failure"
        assert response.payload.config.dshot_speed == 300
        assert response.payload.mutation_id == "disk"

    asyncio.run(run())
    resume.assert_not_called()
    success.assert_not_called()


def test_lost_maintenance_ack_keeps_latch_and_disallows_settings(endpoint, monkeypatch):
    monkeypatch.setattr(endpoint, "_write", AsyncMock())
    monkeypatch.setattr("rov_firmware.pico_control.APPLY_TIMEOUT", 0.005)

    async def run():
        with pytest.raises(TimeoutError):
            await endpoint.enter_maintenance()
        assert endpoint._maintenance
        assert not endpoint._ready
        with pytest.raises(RuntimeError, match="maintenance"):
            await endpoint.apply_config(endpoint.state.rov_config)
        # Serial generation reset cannot silently release maintenance authority.
        endpoint._reset_connection()
        assert endpoint._maintenance

    asyncio.run(run())


def test_rejected_stream_command_is_fail_closed(endpoint):
    endpoint._ready = True
    frame = wire.Frame(wire.CONTROL, endpoint.session, 15, b"")
    endpoint.receive(reply(frame, result=3))
    assert not endpoint._ready
    assert not endpoint.state.system_status.thruster_control_ready
    assert endpoint.session == 0
    assert not endpoint._negotiated
    assert endpoint._next_session() != frame.session


def test_not_ready_stops_reliable_retry_and_excludes_failed_session(
    endpoint, monkeypatch
):
    failed_session = endpoint.session
    sent = []

    async def write(packet):
        frame = wire.decode(packet)
        sent.append(frame)
        endpoint.receive(reply(frame, result=5))

    monkeypatch.setattr(endpoint, "_write", write)
    monkeypatch.setattr(
        "rov_firmware.pico_control.secrets.randbelow", lambda _bound: failed_session - 1
    )

    async def run():
        with pytest.raises(ConnectionError, match="new session required"):
            await endpoint._request(wire.HELLO)

    asyncio.run(run())
    assert len(sent) == 1
    assert endpoint.session == 0
    assert endpoint._next_session() != failed_session
    assert endpoint._settings_generation == endpoint._settings_crc == 0


def test_unencodable_startup_is_neutral_and_corrective_config_applies(
    endpoint, monkeypatch, tmp_path
):
    state = endpoint.state
    state.rov_config.nullspace_vectors = [
        np.zeros(8, dtype=np.float32) for _ in range(9)
    ]
    monkeypatch.setattr(RovConfig, "_config_path", tmp_path / "config.json")
    state.rov_config.save()
    endpoint._negotiated = False
    packets = []

    async def negotiate():
        endpoint._negotiated = True

    async def neutral_write(packet):
        packets.append(wire.decode(packet))

    monkeypatch.setattr(endpoint, "_negotiate", negotiate)
    monkeypatch.setattr(
        endpoint.serial, "ensure_connection", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(endpoint, "_write", neutral_write)
    queue = asyncio.Queue()
    monkeypatch.setattr(config_handler, "get_message_queue", lambda: queue)
    monkeypatch.setattr(websocket_state, "is_client_connected", True)
    events = []
    monkeypatch.setattr(
        config_handler, "toast_success", lambda **_kwargs: events.append("success")
    )
    original_save = RovConfig.save

    def observed_save(config):
        events.append("persisted")
        original_save(config)

    async def applied_write(packet):
        frame = wire.decode(packet)
        if frame.kind == wire.RAW_MOTORS:
            return
        if frame.kind == wire.COMMIT:
            generation, digest = struct.unpack("<II", frame.payload)
            events.append("applied")
            endpoint.receive(reply(frame, generation=generation, digest=digest))
        else:
            endpoint.receive(
                reply(
                    frame,
                    result=wire.STAGED
                    if frame.kind in (wire.BEGIN, wire.CHUNK)
                    else wire.APPLIED,
                )
            )

    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(endpoint.send_loop(), 0.01)
        assert not endpoint._ready
        assert packets and all(
            frame.kind == wire.RAW_MOTORS
            and struct.unpack("<8H", frame.payload) == (1000,) * 8
            for frame in packets
        )
        assert len(state.rov_config.nullspace_vectors) == 9  # No silent truncation.
        monkeypatch.setattr(endpoint, "_write", applied_write)
        monkeypatch.setattr(RovConfig, "save", observed_save)
        await config_handler.handle_set_config(
            state,
            PartialRovConfig(
                nullspace_vectors=[np.zeros(8, dtype=np.float32) for _ in range(8)]
            ),
            "repair",
        )
        response = await queue.get()
        assert response.payload.error is None
        assert len(response.payload.config.nullspace_vectors) == 8
        assert events == ["applied", "persisted"]
        config_handler.handle_confirm_config(state, "repair")
        await asyncio.gather(*state.config_confirmation_tasks)
        assert events == ["applied", "persisted", "success"]

    asyncio.run(run())


def test_failed_depth_setter_warns_without_changing_local_target(endpoint, monkeypatch):
    endpoint.state.regulator.pending_desired_depth = 1.25
    endpoint.state.regulator.desired_depth = 1.25
    endpoint.state.system_status.depth_hold = True
    monkeypatch.setattr(
        endpoint, "set_desired_depth", AsyncMock(side_effect=TimeoutError("ACK lost"))
    )
    warning = Mock()
    monkeypatch.setattr(regulator_handler, "toast_warn", warning)
    asyncio.run(regulator_handler.handle_set_desired_depth(endpoint.state, 4))
    assert (
        endpoint.state.regulator.pending_desired_depth
        == endpoint.state.regulator.desired_depth
        == 1.25
    )
    warning.assert_called_once()
    assert warning.call_args.kwargs["content"].message_key == "toasts_invoke_failed"


def test_clock_rollback_does_not_renew_old_pilot_input(endpoint, monkeypatch):
    endpoint.state.thrusters.last_direction_time = 200
    endpoint.state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
    monkeypatch.setattr("rov_firmware.pico_control.time.time", lambda: 100)
    write = AsyncMock()
    monkeypatch.setattr(endpoint, "_write", write)
    asyncio.run(endpoint._send_direction(1))
    values = struct.unpack("<9fI", wire.decode(write.call_args.args[0]).payload)
    assert values[:8] == (0,) * 8
    assert not values[-1] & 4


def test_clock_rollback_ends_calibration_with_neutral_and_error(endpoint, monkeypatch):
    endpoint.state.system_status.thruster_control_ready = True
    endpoint.state.thrusters.test_thruster = 0
    endpoint.state.thrusters.test_start_time = 200
    monkeypatch.setattr("rov_firmware.pico_control.time.time", lambda: 100)
    write = AsyncMock()
    toast = Mock()
    monkeypatch.setattr(endpoint, "_write", write)
    monkeypatch.setattr("rov_firmware.pico_control.toast_content", toast)
    assert asyncio.run(endpoint._send_test())
    assert endpoint.state.thrusters.test_thruster is None
    frame = wire.decode(write.call_args.args[0])
    assert frame.kind == wire.RAW_MOTORS
    assert struct.unpack("<8H", frame.payload) == (1000,) * 8
    assert toast.call_args.kwargs["variant"].value == "error"
