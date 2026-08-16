import asyncio

from rov_firmware.websocket.receive.state import (
    handle_set_auto_stabilization,
    handle_set_depth_hold,
)


def test_auto_stabilization_set_is_idempotent(rov_state):
    rov_state.system_status.auto_stabilization = True
    rov_state.regulator.desired_pitch = 12.0
    rov_state.regulator.desired_roll = -8.0

    asyncio.run(handle_set_auto_stabilization(rov_state, True))

    assert rov_state.system_status.auto_stabilization is True
    assert rov_state.regulator.desired_pitch == 12.0
    assert rov_state.regulator.desired_roll == -8.0

    asyncio.run(handle_set_auto_stabilization(rov_state, False))

    assert rov_state.system_status.auto_stabilization is False
    assert rov_state.regulator.desired_pitch == 0.0
    assert rov_state.regulator.desired_roll == 0.0


def test_depth_hold_set_only_captures_depth_on_enable_transition(rov_state):
    rov_state.pressure.depth = 7.5

    asyncio.run(handle_set_depth_hold(rov_state, True))
    assert rov_state.system_status.depth_hold is True
    assert rov_state.regulator.desired_depth == 7.5

    rov_state.pressure.depth = 11.0
    asyncio.run(handle_set_depth_hold(rov_state, True))
    assert rov_state.regulator.desired_depth == 7.5

    asyncio.run(handle_set_depth_hold(rov_state, False))
    assert rov_state.system_status.depth_hold is False
    assert rov_state.regulator.pending_desired_depth is None
