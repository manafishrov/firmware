from rov_firmware.websocket.send import status


def test_status_reports_pi_undervoltage(rov_state, monkeypatch):
    monkeypatch.setattr(status, "is_pi_undervoltage_detected", lambda: True)

    message = status.build_status_update(rov_state)

    assert message.payload.pi_undervoltage is True
    assert message.model_dump(by_alias=True)["payload"]["piUndervoltage"] is True


def test_status_reports_read_only_device_versions(rov_state):
    rov_state.device_info.mcu_firmware_version = "1.2.3-rc.1"
    rov_state.device_info.esc_firmware_versions = ["2.20.0-rc.3"] * 8

    payload = status.build_status_update(rov_state).model_dump(by_alias=True)["payload"]

    assert payload["deviceInfo"]["mcuFirmwareVersion"] == "1.2.3-rc.1"
    assert payload["deviceInfo"]["escFirmwareVersions"] == ["2.20.0-rc.3"] * 8
