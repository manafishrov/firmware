from rov_firmware.websocket.send import status


def test_status_reports_pi_undervoltage(rov_state, monkeypatch):
    monkeypatch.setattr(status, "is_pi_undervoltage_detected", lambda: True)

    message = status.build_status_update(rov_state)

    assert message.payload.pi_undervoltage is True
    assert message.model_dump(by_alias=True)["payload"]["piUndervoltage"] is True
