from rov_firmware.models.config import CurrentSensingMode
from rov_firmware.websocket.send import status


def test_status_reports_pi_undervoltage(rov_state, monkeypatch):
    monkeypatch.setattr(status, "is_pi_undervoltage_detected", lambda: True)

    message = status.build_status_update(rov_state)

    assert message.payload.pi_undervoltage is True
    assert message.model_dump(by_alias=True)["payload"]["piUndervoltage"] is True


def test_status_reports_thruster_control_readiness(rov_state):
    rov_state.system_status.thruster_control_ready = True

    payload = status.build_status_update(rov_state).model_dump(by_alias=True)["payload"]

    assert payload["thrusterControlReady"] is True


def test_status_reports_read_only_device_versions(rov_state):
    rov_state.device_info.mcu_firmware_version = "1.2.3-rc.1"
    rov_state.device_info.esc_firmware_versions = ["2.20.0-rc.3"] * 8

    payload = status.build_status_update(rov_state).model_dump(by_alias=True)["payload"]

    assert payload["deviceInfo"]["mcuFirmwareVersion"] == "1.2.3-rc.1"
    assert payload["deviceInfo"]["escFirmwareVersions"] == ["2.20.0-rc.3"] * 8
    assert payload["escFirmwareUpdate"]["stage"] == "idle"


def test_status_counts_each_shared_current_bus_once(rov_state):
    rov_state.rov_config.current_sensing_mode = CurrentSensingMode.SHARED_BUS
    rov_state.mcu_telemetry.current = [3, 3, 3, 3, 7, 7, 7, 7]
    rov_state.mcu_telemetry.current_valid = [True] * 8

    payload = status.build_status_update(rov_state).payload

    assert payload.current_draw == 10


def test_status_averages_only_fresh_shared_bus_readings(rov_state):
    rov_state.rov_config.current_sensing_mode = CurrentSensingMode.SHARED_BUS
    rov_state.mcu_telemetry.current = [2, 3, 0, 0, 8, 0, 0, 0]
    rov_state.mcu_telemetry.current_valid = [
        True,
        True,
        False,
        False,
        True,
        False,
        False,
        False,
    ]

    payload = status.build_status_update(rov_state).payload

    assert payload.current_draw == 11


def test_status_sums_fresh_per_motor_current(rov_state):
    rov_state.rov_config.current_sensing_mode = CurrentSensingMode.PER_MOTOR
    rov_state.mcu_telemetry.current = [1, 2, 3, 4, 5, 6, 7, 8]
    rov_state.mcu_telemetry.current_valid = [
        True,
        True,
        False,
        True,
        True,
        True,
        True,
        True,
    ]

    payload = status.build_status_update(rov_state).payload

    assert payload.current_draw == 33
