import json

import numpy as np
from pydantic import ValidationError
import pytest

from rov_firmware.models.config import (
    CURRENT_FIRMWARE_VERSION,
    AxisConfig,
    PartialRovConfig,
    Power,
    RovConfig,
    ThrusterPinSetup,
    compare_semver,
    parse_semver,
)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.3", (1, 2, 3)),
        ("1.0", (1, 0, 0)),
        ("", (0, 0, 0)),
        ("abc", (0, 0, 0)),
    ],
)
def test_parse_semver(version, expected):
    assert parse_semver(version) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("1.0.0", "1.0.1", -1),
        ("1.2.3", "1.2.3", 0),
        ("2.0.0", "1.9.9", 1),
    ],
)
def test_compare_semver(left, right, expected):
    assert compare_semver(left, right) == expected


def test_axis_config_accepts_float_values():
    axis = AxisConfig(kp=1.5, ki=0.25, kd=0.125, rate=2.0)

    assert axis.kp == pytest.approx(1.5)
    assert axis.ki == pytest.approx(0.25)
    assert axis.kd == pytest.approx(0.125)
    assert axis.rate == pytest.approx(2.0)


def test_power_validators_accept_positive_voltage_and_zero_resistance():
    power = Power(
        thrusters_limit=30,
        actions_limit=40,
        regulator_limit=50,
        min_battery_voltage=14.0,
        max_battery_voltage=21.5,
        internal_resistance=0.0,
    )

    assert power.min_battery_voltage == pytest.approx(14.0)
    assert power.max_battery_voltage == pytest.approx(21.5)
    assert power.internal_resistance == pytest.approx(0.0)


@pytest.mark.parametrize("voltage", [0.0, -1.0])
def test_power_rejects_non_positive_battery_voltage(voltage):
    with pytest.raises(ValidationError):
        Power(
            thrusters_limit=30,
            actions_limit=40,
            regulator_limit=50,
            min_battery_voltage=voltage,
            max_battery_voltage=21.5,
            internal_resistance=0.1,
        )


def test_power_rejects_negative_internal_resistance():
    with pytest.raises(ValidationError):
        Power(
            thrusters_limit=30,
            actions_limit=40,
            regulator_limit=50,
            min_battery_voltage=14.0,
            max_battery_voltage=21.5,
            internal_resistance=-0.01,
        )


@pytest.mark.parametrize("dshot_speed", [150, 300, 600, 1200])
def test_rov_config_accepts_supported_dshot_speeds(dshot_speed):
    config = RovConfig(dshot_speed=dshot_speed)

    assert config.dshot_speed == dshot_speed


@pytest.mark.parametrize("dshot_speed", [0, 100, 450, 2400])
def test_rov_config_rejects_unsupported_dshot_speeds(dshot_speed):
    with pytest.raises(ValidationError):
        RovConfig(dshot_speed=dshot_speed)


def test_thruster_pin_setup_converts_lists_to_numpy_arrays():
    pin_setup = ThrusterPinSetup.model_validate(
        {
            "identifiers": [7, 6, 5, 4, 3, 2, 1, 0],
            "spinDirections": [1, -1, 1, -1, 1, -1, 1, -1],
        }
    )

    assert isinstance(pin_setup.identifiers, np.ndarray)
    assert isinstance(pin_setup.spin_directions, np.ndarray)
    assert pin_setup.identifiers.dtype == np.int8
    assert pin_setup.spin_directions.dtype == np.int8
    assert np.array_equal(pin_setup.identifiers, np.array([7, 6, 5, 4, 3, 2, 1, 0]))
    assert np.array_equal(
        pin_setup.spin_directions,
        np.array([1, -1, 1, -1, 1, -1, 1, -1]),
    )


def test_rov_config_json_round_trip_uses_camel_case_aliases():
    config = RovConfig()

    serialized = json.loads(config.model_dump_json(by_alias=True))

    assert "firmwareVersion" in serialized
    assert "mcuFirmwareVersion" in serialized
    assert "dshotSpeed" in serialized
    assert "ipAddress" in serialized
    assert "websocketPort" in serialized
    assert "thrusterPinSetup" in serialized
    assert "spinDirections" in serialized["thrusterPinSetup"]

    round_tripped = RovConfig.model_validate(serialized)

    assert round_tripped.firmware_version == CURRENT_FIRMWARE_VERSION
    assert round_tripped.dshot_speed == config.dshot_speed
    assert round_tripped.ip_address == config.ip_address
    assert round_tripped.websocket_port == config.websocket_port
    assert np.array_equal(
        np.asarray(round_tripped.thruster_pin_setup.identifiers),
        np.asarray(config.thruster_pin_setup.identifiers),
    )
    assert np.array_equal(
        np.asarray(round_tripped.thruster_pin_setup.spin_directions),
        np.asarray(config.thruster_pin_setup.spin_directions),
    )


def test_partial_rov_config_with_all_none_fields_serializes_to_minimal_json():
    serialized = json.loads(
        PartialRovConfig().model_dump_json(by_alias=True, exclude_none=True)
    )

    assert serialized == {}


def test_partial_rov_config_serializes_only_set_fields():
    serialized = json.loads(
        PartialRovConfig(
            ip_address="192.168.2.10",
            dshot_speed=600,
        ).model_dump_json(by_alias=True, exclude_none=True)
    )

    assert serialized == {
        "ipAddress": "192.168.2.10",
        "dshotSpeed": 600,
    }


def test_rov_config_defaults_are_sensible():
    config = RovConfig()

    assert config.ip_address == "10.10.10.10"
    assert config.websocket_port == 9000
    assert config.dshot_speed == 300
    assert config.thruster_protocol == "dshot"
