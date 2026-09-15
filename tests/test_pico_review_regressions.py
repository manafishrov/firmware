"""Regressions for maintenance ownership, smoothing gaps and cancel ordering."""

import asyncio
import contextlib
from pathlib import Path
import struct
import time
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from rov_firmware import esc_firmware, pico_protocol as wire
from rov_firmware.models.config import ThrusterProtocol
from rov_firmware.pico_control import CONTROL_INTERVAL, PicoControl
from rov_firmware.serial import SerialManager
from rov_firmware.websocket.receive import actions


@pytest.fixture
def endpoint(rov_state):
    control = PicoControl(rov_state, SerialManager(rov_state))
    control._reset_connection()
    control.session = 123
    control._negotiated = control._ready = True
    rov_state.system_status.thruster_control_ready = True
    rov_state.pico = control
    return control


@pytest.mark.parametrize("already_in_maintenance", [False, True])
def test_preflight_rejection_preserves_pico_authority(
    endpoint, monkeypatch, already_in_maintenance
):
    state = endpoint.state
    state.rov_config.thruster_protocol = ThrusterProtocol.PWM
    endpoint._maintenance = already_in_maintenance
    before = (endpoint.session, endpoint._negotiated, endpoint._ready)
    monkeypatch.setattr(esc_firmware, "_abort_update", AsyncMock())

    assert not asyncio.run(
        esc_firmware.flash_esc_firmware(state, endpoint.serial, show_toasts=False)
    )
    assert (endpoint.session, endpoint._negotiated, endpoint._ready) == before
    assert endpoint._maintenance == already_in_maintenance
    assert state.system_status.thruster_control_ready
    assert not state.mcu_flashing
    assert not state.esc_firmware_update.active


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "entry_failure"])
def test_started_esc_update_always_releases_its_maintenance(
    endpoint, monkeypatch, outcome
):
    state = endpoint.state
    release = (Path("bundled.bin"), "2.21.0", b"validated image")
    monkeypatch.setattr(
        esc_firmware, "_preflight_update", AsyncMock(return_value=release)
    )
    monkeypatch.setattr(esc_firmware, "_DISARM_SETTLE_S", 0)
    monkeypatch.setattr(esc_firmware, "_abort_update", AsyncMock())
    monkeypatch.setattr(esc_firmware, "clear_esc_firmware_recovery_required", Mock())
    monkeypatch.setattr(endpoint.serial, "get_reader", Mock())
    monkeypatch.setattr(endpoint.serial, "get_writer", Mock())
    monkeypatch.setattr(endpoint, "_write", AsyncMock())
    request = AsyncMock(
        side_effect=TimeoutError("lost maintenance ACK")
        if outcome == "entry_failure"
        else None
    )
    monkeypatch.setattr(endpoint, "_request", request)

    async def upload(*_args, **_kwargs):
        assert endpoint._maintenance
        assert state.mcu_flashing
        if outcome == "failure":
            msg = "upload failed"
            raise esc_firmware.EscFirmwareUpdateError(msg)
        if outcome == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(esc_firmware, "_run_update", upload)

    async def run():
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await esc_firmware.flash_esc_firmware(
                    state, endpoint.serial, show_toasts=False
                )
        else:
            assert await esc_firmware.flash_esc_firmware(
                state, endpoint.serial, show_toasts=False
            ) == (outcome == "success")

    asyncio.run(run())
    request.assert_awaited_once_with(wire.ENTER_MAINTENANCE)
    assert not endpoint._maintenance
    assert not endpoint._ready
    assert not endpoint._negotiated
    assert endpoint.session == 0
    assert not state.mcu_flashing
    assert not state.esc_firmware_update.active


@pytest.mark.parametrize("gap", ["expiry", "invalid", "rollback", "reconnect"])
def test_smoothing_resumes_from_neutral_after_gap(endpoint, monkeypatch, gap):
    state = endpoint.state
    state.rov_config.smoothing_factor = 1
    state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
    state.thrusters.last_direction_time = 100
    clock = 100.0
    monkeypatch.setattr("rov_firmware.pico_control.time.time", lambda: clock)
    write = AsyncMock()
    monkeypatch.setattr(endpoint, "_write", write)
    endpoint._previous_direction.fill(0.75)
    endpoint._last_source = 1

    async def run():
        nonlocal clock
        await endpoint._send_direction(1 + CONTROL_INTERVAL)
        if gap == "reconnect":
            endpoint._reset_connection()
        else:
            if gap == "expiry":
                clock = 101
            elif gap == "rollback":
                clock = 99
            else:
                state.thrusters.direction_vector[0] = np.nan
            await endpoint._send_direction(2)
            invalid = struct.unpack(
                "<9fI", wire.decode(write.call_args.args[0]).payload
            )
            assert invalid[:8] == (0,) * 8
            assert not invalid[-1] & 4
        clock = 102
        state.thrusters.last_direction_time = clock
        state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
        await endpoint._send_direction(3)

    asyncio.run(run())
    resumed = struct.unpack("<9fI", wire.decode(write.call_args.args[0]).payload)
    assert resumed[:8] == pytest.approx((CONTROL_INTERVAL,) * 8)
    assert resumed[-1] & 4
    if gap == "reconnect":
        assert resumed[8] == pytest.approx(CONTROL_INTERVAL)


def test_cancel_neutral_precedes_pilot_when_pressure_drain_holds_gate(
    endpoint, monkeypatch
):
    """Exercise the real send loop and write lock, suspending only USB drain."""
    state = endpoint.state
    state.thrusters.test_thruster = 0
    state.thrusters.direction_vector = np.ones(8, dtype=np.float32)
    state.rov_config.smoothing_factor = 0
    monkeypatch.setattr(
        endpoint.serial, "ensure_connection", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(actions, "toast_content", Mock())
    monkeypatch.setattr("rov_firmware.pico_control.toast_content", Mock())

    async def run():
        pressure_entered = asyncio.Event()
        pressure_release = asyncio.Event()
        neutral_entered = asyncio.Event()
        neutral_release = asyncio.Event()
        pilot_sent = asyncio.Event()
        frames = []

        class Writer:
            def write(self, packet):
                frames.append(wire.decode(packet))
                if frames[-1].kind == wire.CONTROL:
                    pilot_sent.set()

            async def drain(self):
                frame = frames[-1]
                if frame.kind == wire.PRESSURE:
                    pressure_entered.set()
                    await pressure_release.wait()
                elif frame.kind == wire.RAW_MOTORS and frame.payload == struct.pack(
                    "<8H", *([1000] * 8)
                ):
                    neutral_entered.set()
                    await neutral_release.wait()

        monkeypatch.setattr(endpoint.serial, "get_writer", Writer)
        endpoint._last_telemetry = endpoint._last_raw_imu = time.monotonic()
        state.thrusters.last_direction_time = time.time()
        loop = asyncio.create_task(endpoint.send_loop())
        cancel = None
        try:
            await asyncio.wait_for(pressure_entered.wait(), 1)
            assert endpoint._gate.locked()
            cancel = asyncio.create_task(actions.handle_cancel_thruster_test(state, 0))
            await asyncio.sleep(
                0
            )  # Handler reaches the gate while real drain is blocked.
            assert state.thrusters.test_request_id == 1
            assert not cancel.done()
            pressure_release.set()
            await asyncio.wait_for(neutral_entered.wait(), 1)
            assert not pilot_sent.is_set(), [frame.kind for frame in frames]
            neutral_release.set()
            await asyncio.wait_for(cancel, 1)
            await asyncio.wait_for(pilot_sent.wait(), 1)
            kinds = [frame.kind for frame in frames]
            neutral_index = next(
                i
                for i, frame in enumerate(frames)
                if frame.kind == wire.RAW_MOTORS
                and frame.payload == struct.pack("<8H", *([1000] * 8))
            )
            assert neutral_index < kinds.index(wire.CONTROL)
            assert state.thrusters.test_thruster is None
        finally:
            loop.cancel()
            if cancel is not None:
                cancel.cancel()
            for task in (loop, cancel):
                if task is not None:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    asyncio.run(run())


def test_new_test_request_survives_cancel_waiting_for_gate(endpoint, monkeypatch):
    state = endpoint.state
    state.thrusters.test_thruster = 0
    monkeypatch.setattr(endpoint, "neutral", AsyncMock())
    monkeypatch.setattr(actions, "toast_content", Mock())

    async def run():
        async with endpoint._gate:
            cancel = asyncio.create_task(actions.handle_cancel_thruster_test(state, 0))
            await asyncio.sleep(0)
            await actions.handle_start_thruster_test(state, 3)
        await cancel
        assert state.thrusters.test_thruster == 3
        assert state.thrusters.test_request_id == 2
        endpoint.neutral.assert_awaited_once()

    asyncio.run(run())
