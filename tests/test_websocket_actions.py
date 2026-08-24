import asyncio

from rov_firmware.websocket.receive import actions


def test_thruster_test_is_rejected_until_control_is_ready(rov_state, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        actions, "toast_content", lambda **kwargs: toasts.append(kwargs)
    )

    asyncio.run(actions.handle_start_thruster_test(rov_state, 4))

    assert rov_state.thrusters.test_thruster is None
    assert toasts[0]["variant"].value == "error"
    assert toasts[0]["content"].message_key == "toasts_thruster_test_unavailable"


def test_thruster_test_is_queued_without_starting_countdown(rov_state, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        actions, "toast_content", lambda **kwargs: toasts.append(kwargs)
    )
    rov_state.system_status.thruster_control_ready = True

    asyncio.run(actions.handle_start_thruster_test(rov_state, 4))

    assert rov_state.thrusters.test_thruster == 4
    assert rov_state.thrusters.test_start_time is None
    assert toasts == []
