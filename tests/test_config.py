import json

import numpy as np
from pydantic import ValidationError
import pytest

from rov_firmware.models.config import (
    CURRENT_FIRMWARE_VERSION,
    AxisConfig,
    Camera,
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


_NULLSPACE_VECTORS = [
    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
]


@pytest.mark.parametrize("model_cls", [RovConfig, PartialRovConfig])
def test_nullspace_vectors_validator_converts_nested_list_to_list_of_float32_arrays(
    model_cls,
):
    config = model_cls.model_validate({"nullspaceVectors": _NULLSPACE_VECTORS})

    assert isinstance(config.nullspace_vectors, list)
    assert len(config.nullspace_vectors) == 2
    for i, row in enumerate(config.nullspace_vectors):
        assert isinstance(row, np.ndarray)
        assert row.dtype == np.float32
        assert row.shape == (8,)
        assert np.array_equal(row, np.array(_NULLSPACE_VECTORS[i], dtype=np.float32))


def test_nullspace_vectors_validator_none_gives_empty_list_for_rov_config():
    config = RovConfig.model_validate({"nullspaceVectors": None})

    assert config.nullspace_vectors == []


def test_nullspace_vectors_validator_none_passes_unchanged_for_partial_rov_config():
    config = PartialRovConfig.model_validate({"nullspaceVectors": None})

    assert config.nullspace_vectors is None


def test_rov_config_round_trip_nullspace_vectors_empty():
    config = RovConfig()
    assert config.nullspace_vectors == []

    serialized = json.loads(config.model_dump_json(by_alias=True))

    assert "nullspaceVectors" in serialized
    assert serialized["nullspaceVectors"] == []

    round_tripped = RovConfig.model_validate(serialized)
    assert round_tripped.nullspace_vectors == []


def test_rov_config_round_trip_nullspace_vectors_populated():
    config = RovConfig(
        nullspace_vectors=[
            np.array(row, dtype=np.float32) for row in _NULLSPACE_VECTORS
        ]
    )

    serialized = json.loads(config.model_dump_json(by_alias=True))

    assert "nullspaceVectors" in serialized
    assert len(serialized["nullspaceVectors"]) == 2
    assert len(serialized["nullspaceVectors"][0]) == 8

    round_tripped = RovConfig.model_validate(serialized)
    assert isinstance(round_tripped.nullspace_vectors, list)
    assert len(round_tripped.nullspace_vectors) == 2
    for i, row in enumerate(round_tripped.nullspace_vectors):
        assert isinstance(row, np.ndarray)
        assert row.dtype == np.float32
        assert np.array_equal(row, np.array(_NULLSPACE_VECTORS[i], dtype=np.float32))


def test_camera_defaults_match_stream_baseline():
    camera = Camera()

    assert camera.width == 1440
    assert camera.height == 1080
    assert camera.framerate == 40
    assert camera.crop_fov is False
    assert camera.bitrate == 20000000
    assert camera.keyframe_interval == 30
    assert camera.profile == "baseline"
    assert camera.level == "4.2"
    assert camera.denoise == "off"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("width", 999999, 4056),
        ("width", 10, 160),
        ("width", 1281, 1280),
        ("height", 999999, 3040),
        # At the default 1440x1080 (full-FOV only, crop_fov defaults False),
        # the ceiling is the encoder's ~40.15fps rounded down to 40.
        ("framerate", 999, 40),
        ("framerate", 0, 1),
        ("bitrate", 10**12, 25000000),
        ("bitrate", 1, 1000000),
        ("keyframe_interval", 100000, 300),
        ("keyframe_interval", 0, 1),
    ],
)
def test_camera_clamps_out_of_range_integers(field, value, expected):
    camera = Camera.model_validate({field: value})

    assert getattr(camera, field) == expected


def test_camera_framerate_ceiling_depends_on_crop_fov_and_resolution():
    # A small resolution with crop_fov off still only gets the full-FOV
    # sensor mode's 40fps ceiling.
    scaled = Camera.model_validate(
        {"width": 320, "height": 240, "crop_fov": False, "framerate": 999}
    )
    assert scaled.framerate == 40

    # The same resolution with crop_fov on can use the faster crop sensor
    # mode, up to its 120fps hardware ceiling.
    cropped = Camera.model_validate(
        {"width": 320, "height": 240, "crop_fov": True, "framerate": 999}
    )
    assert cropped.framerate == 120

    # A resolution too large for the crop mode falls back to the full-FOV
    # ceiling even with crop_fov on.
    max_resolution = Camera.model_validate(
        {"width": 1440, "height": 1080, "crop_fov": True, "framerate": 999}
    )
    assert max_resolution.framerate == 40

    # A mid-size resolution with crop_fov on is limited by the H.264 encoder's
    # macroblock rate before the sensor's 120fps ceiling ever applies.
    mid_resolution = Camera.model_validate(
        {"width": 1280, "height": 960, "crop_fov": True, "framerate": 999}
    )
    assert mid_resolution.framerate == 51


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("exposure_value", 100.0, 8.0),
        ("exposure_value", -100.0, -8.0),
        ("brightness", 5.0, 1.0),
        ("brightness", -5.0, -1.0),
        ("contrast", 100.0, 15.0),
        ("saturation", -5.0, 0.0),
        ("sharpness", 100.0, 15.0),
    ],
)
def test_camera_clamps_out_of_range_floats(field, value, expected):
    camera = Camera.model_validate({field: value})

    assert getattr(camera, field) == expected


def test_camera_rejects_odd_dimensions_by_rounding_down():
    camera = Camera(width=1921, height=1081)

    assert camera.width == 1920
    assert camera.height == 1080


def test_camera_falls_back_invalid_rotation_to_zero():
    assert Camera(rotation=90).rotation == 0
    assert Camera(rotation=180).rotation == 180


def test_rov_config_serializes_camera_with_camel_case_aliases():
    serialized = json.loads(RovConfig().model_dump_json(by_alias=True))

    assert "camera" in serialized
    assert serialized["camera"]["keyframeInterval"] == 30
    assert serialized["camera"]["exposureValue"] == 0.0

    round_tripped = RovConfig.model_validate(serialized)
    assert round_tripped.camera == RovConfig().camera


def test_partial_rov_config_accepts_camera_update():
    partial = PartialRovConfig.model_validate({"camera": {"framerate": 24}})

    assert partial.camera is not None
    assert partial.camera.framerate == 24
