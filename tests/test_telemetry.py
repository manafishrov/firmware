from rov_firmware.websocket.send.telemetry import build_telemetry


def test_signal_quality_distinguishes_zero_from_unavailable(rov_state):
    rov_state.mcu_telemetry.signal_quality[0] = 0.0
    rov_state.mcu_telemetry.signal_quality_valid[0] = True
    rov_state.mcu_telemetry.signal_quality[1] = 75.5
    rov_state.mcu_telemetry.signal_quality_valid[1] = False

    payload = build_telemetry(rov_state).model_dump(by_alias=True)["payload"]

    assert payload["thrusterSignalQualities"][0] == 0.0
    assert payload["thrusterSignalQualities"][1] is None
