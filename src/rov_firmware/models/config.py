"""Configuration models for the ROV firmware."""

from enum import StrEnum
import json
from pathlib import Path
import secrets
import tempfile
import tomllib
from typing import Annotated, Any, ClassVar

import numpy as np
from numpy.typing import NDArray as NumpyNDArray
from numpydantic import NDArraySchema
from pydantic import Field, field_validator, model_validator

from .base import CamelCaseModel


_ROV_NAME_HEX_LENGTH = 4


def _generate_rov_name() -> str:
    return f"Manafish-{secrets.token_hex(_ROV_NAME_HEX_LENGTH)}"


_pyproject_path = Path(__file__).parents[3] / "pyproject.toml"
with _pyproject_path.open("rb") as _f:
    _pyproject = tomllib.load(_f)
CURRENT_FIRMWARE_VERSION = _pyproject["project"]["version"]

_MAJOR = 0
_MINOR = 1
_PATCH = 2


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse semver string into (major, minor, patch) tuple."""
    parts = version.split(".")
    major = int(parts[_MAJOR]) if len(parts) > _MAJOR and parts[_MAJOR].isdigit() else 0
    minor = int(parts[_MINOR]) if len(parts) > _MINOR and parts[_MINOR].isdigit() else 0
    patch = int(parts[_PATCH]) if len(parts) > _PATCH and parts[_PATCH].isdigit() else 0
    return (major, minor, patch)


def compare_semver(a: str, b: str) -> int:
    """Compare two semver strings. Returns -1, 0, or 1."""
    a_tuple = parse_semver(a)
    b_tuple = parse_semver(b)
    if a_tuple < b_tuple:
        return -1
    elif a_tuple > b_tuple:
        return 1
    return 0


def apply_migrations(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply config migrations based on firmware version."""
    firmware_version = raw.get("firmwareVersion", "0.0.0")

    if compare_semver(firmware_version, "1.1.0") == -1:
        raw.setdefault("nullspaceVectors", [])
        raw["firmwareVersion"] = "1.1.0"

    return raw


class McuBoard(StrEnum):
    """Enum for supported MCU boards."""

    PICO = "pico"
    PICO2 = "pico2"


class ThrusterProtocol(StrEnum):
    """Enum for supported thruster output protocols."""

    PWM = "pwm"
    DSHOT = "dshot"


class CurrentSensingMode(StrEnum):
    """Enum for ESC current sensing modes."""

    PER_MOTOR = "perMotor"
    SHARED_BUS = "sharedBus"


class FluidType(StrEnum):
    """Enum for fluid types."""

    FRESHWATER = "freshwater"
    SALTWATER = "saltwater"


class ThrusterPinSetup(CamelCaseModel):
    """Model for thruster pin setup."""

    identifiers: Annotated[np.ndarray, NDArraySchema((8,), np.int8)]
    spin_directions: Annotated[np.ndarray, NDArraySchema((8,), np.int8)]

    @field_validator("identifiers", mode="before")
    @classmethod
    def validate_identifiers(cls, v: list[int]) -> NumpyNDArray[np.int8]:
        """Validate and convert identifiers to numpy array."""
        return np.array(v, dtype=np.int8)

    @field_validator("spin_directions", mode="before")
    @classmethod
    def validate_spin_directions(cls, v: list[int]) -> NumpyNDArray[np.int8]:
        """Validate and convert spin directions to numpy array."""
        return np.array(v, dtype=np.int8)


class AxisConfig(CamelCaseModel):
    """Configuration for a single regulator axis."""

    kp: float
    ki: float
    kd: float
    rate: float = 1.0


class Regulator(CamelCaseModel):
    """Regulator configuration."""

    pitch: AxisConfig
    roll: AxisConfig
    yaw: AxisConfig
    depth: AxisConfig
    fpv_mode: bool


class DirectionCoefficients(CamelCaseModel):
    """Direction coefficients for movement."""

    surge: float
    sway: float
    heave: float


class Power(CamelCaseModel):
    """Power configuration."""

    thrusters_limit: int
    actions_limit: int
    regulator_limit: int
    min_battery_voltage: float
    max_battery_voltage: float
    internal_resistance: float = 0.1

    @field_validator("min_battery_voltage", "max_battery_voltage", mode="after")
    @classmethod
    def validate_battery_voltage(cls, v: float) -> float:
        """Validate that battery voltage is positive."""
        if v <= 0:
            msg = "Battery voltage must be positive"
            raise ValueError(msg)
        return v

    @field_validator("internal_resistance", mode="after")
    @classmethod
    def validate_internal_resistance(cls, v: float) -> float:
        """Validate that internal resistance is non-negative."""
        if v < 0:
            msg = "Internal resistance must be non-negative"
            raise ValueError(msg)
        return v


class H264Profile(StrEnum):
    """Enum for supported H.264 encoder profiles."""

    BASELINE = "baseline"
    MAIN = "main"
    HIGH = "high"


class H264Level(StrEnum):
    """Enum for supported H.264 encoder levels."""

    LEVEL_4_0 = "4"
    LEVEL_4_1 = "4.1"
    LEVEL_4_2 = "4.2"


class AwbMode(StrEnum):
    """Enum for camera auto white balance modes."""

    AUTO = "auto"
    INCANDESCENT = "incandescent"
    TUNGSTEN = "tungsten"
    FLUORESCENT = "fluorescent"
    INDOOR = "indoor"
    DAYLIGHT = "daylight"
    CLOUDY = "cloudy"


class DenoiseMode(StrEnum):
    """Enum for camera denoise modes."""

    AUTO = "auto"
    OFF = "off"
    CDN_OFF = "cdn_off"
    CDN_FAST = "cdn_fast"
    CDN_HQ = "cdn_hq"


_MIN_FRAME_DIMENSION = 160
_MAX_FRAME_WIDTH = 4056
_MAX_FRAME_HEIGHT = 3040
_MIN_FRAMERATE = 1
_MAX_FRAMERATE = 60
_MIN_BITRATE = 1_000_000
_MAX_BITRATE = 25_000_000
_MIN_KEYFRAME_INTERVAL = 1
_MAX_KEYFRAME_INTERVAL = 300
_VALID_ROTATIONS = (0, 180)
_MIN_EXPOSURE_VALUE = -8.0
_MAX_EXPOSURE_VALUE = 8.0
_MIN_BRIGHTNESS = -1.0
_MAX_BRIGHTNESS = 1.0
_MIN_IMAGE_ADJUSTMENT = 0.0
_MAX_IMAGE_ADJUSTMENT = 15.0


def _clamp_int(value: int, low: int, high: int) -> int:
    """Clamp an integer into the inclusive ``[low, high]`` range."""
    return max(low, min(value, high))


def _clamp_float(value: float, low: float, high: float) -> float:
    """Clamp a float into the inclusive ``[low, high]`` range."""
    return max(low, min(value, high))


def _to_even(value: int) -> int:
    """Round an integer down to the nearest even number.

    Hardware H.264 encoders require even frame dimensions.
    """
    return value - (value % 2)


class Camera(CamelCaseModel):
    """Camera capture and H.264 stream configuration.

    Every numeric field is clamped to an encoder-safe range so an out-of-range
    value can never prevent the camera stream from starting.
    """

    width: int = 1920
    height: int = 1080
    framerate: int = 30
    bitrate: int = 20_000_000
    keyframe_interval: int = 30
    profile: H264Profile = H264Profile.BASELINE
    level: H264Level = H264Level.LEVEL_4_2
    rotation: int = 0
    hflip: bool = False
    vflip: bool = False
    awb: AwbMode = AwbMode.AUTO
    exposure_value: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    denoise: DenoiseMode = DenoiseMode.AUTO

    @model_validator(mode="after")
    def clamp_ranges(self) -> "Camera":
        """Clamp all numeric fields to encoder-safe ranges."""
        self.width = _to_even(
            _clamp_int(self.width, _MIN_FRAME_DIMENSION, _MAX_FRAME_WIDTH)
        )
        self.height = _to_even(
            _clamp_int(self.height, _MIN_FRAME_DIMENSION, _MAX_FRAME_HEIGHT)
        )
        self.framerate = _clamp_int(self.framerate, _MIN_FRAMERATE, _MAX_FRAMERATE)
        self.bitrate = _clamp_int(self.bitrate, _MIN_BITRATE, _MAX_BITRATE)
        self.keyframe_interval = _clamp_int(
            self.keyframe_interval,
            _MIN_KEYFRAME_INTERVAL,
            _MAX_KEYFRAME_INTERVAL,
        )
        if self.rotation not in _VALID_ROTATIONS:
            self.rotation = 0
        self.exposure_value = _clamp_float(
            self.exposure_value, _MIN_EXPOSURE_VALUE, _MAX_EXPOSURE_VALUE
        )
        self.brightness = _clamp_float(
            self.brightness, _MIN_BRIGHTNESS, _MAX_BRIGHTNESS
        )
        self.contrast = _clamp_float(
            self.contrast, _MIN_IMAGE_ADJUSTMENT, _MAX_IMAGE_ADJUSTMENT
        )
        self.saturation = _clamp_float(
            self.saturation, _MIN_IMAGE_ADJUSTMENT, _MAX_IMAGE_ADJUSTMENT
        )
        self.sharpness = _clamp_float(
            self.sharpness, _MIN_IMAGE_ADJUSTMENT, _MAX_IMAGE_ADJUSTMENT
        )
        return self


class RovConfig(CamelCaseModel):
    """Main ROV configuration."""

    firmware_version: str = CURRENT_FIRMWARE_VERSION
    mcu_firmware_version: str = ""
    rov_name: str = Field(default_factory=_generate_rov_name)
    mcu_board: McuBoard = McuBoard.PICO
    thruster_protocol: ThrusterProtocol = ThrusterProtocol.DSHOT
    dshot_speed: int = 300
    current_sensing_mode: CurrentSensingMode = CurrentSensingMode.SHARED_BUS
    fluid_type: FluidType = FluidType.SALTWATER
    smoothing_factor: float = 0.0
    thruster_pin_setup: ThrusterPinSetup = ThrusterPinSetup(
        identifiers=np.array([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int8),
        spin_directions=np.array([1, 1, 1, 1, 1, 1, 1, 1], dtype=np.int8),
    )
    thruster_allocation: Annotated[np.ndarray, NDArraySchema((8, 8), np.float32)] = (
        np.array(
            (
                (1, 1, 0, 0, -1, 0, 0, 0),
                (1, -1, 0, 0, 1, 0, 0, 0),
                (0, 0, 1, 1, 0, 1, 0, 0),
                (0, 0, 1, 1, 0, -1, 0, 0),
                (0, 0, 1, -1, 0, 1, 0, 0),
                (0, 0, 1, -1, 0, -1, 0, 0),
                (-1, -1, 0, 0, 1, 0, 0, 0),
                (-1, 1, 0, 0, -1, 0, 0, 0),
            ),
            dtype=np.float32,
        )
    )

    nullspace_vectors: list[Annotated[np.ndarray, NDArraySchema((8,), np.float32)]] = (
        Field(default_factory=list)
    )

    regulator: Regulator = Regulator(
        pitch=AxisConfig(kp=6, ki=2, kd=0.6, rate=120.0),
        roll=AxisConfig(kp=6, ki=2, kd=0.6, rate=120.0),
        yaw=AxisConfig(kp=6, ki=2, kd=0.6, rate=120.0),
        depth=AxisConfig(kp=6, ki=2, kd=0.6, rate=0.5),
        fpv_mode=False,
    )
    direction_coefficients: DirectionCoefficients = DirectionCoefficients(
        surge=1,
        sway=1,
        heave=1,
    )
    power: Power = Power(
        thrusters_limit=30,
        actions_limit=50,
        regulator_limit=30,
        min_battery_voltage=16,
        max_battery_voltage=20.5,
    )
    camera: Camera = Camera()
    ip_address: str = "10.10.10.10"
    websocket_port: int = 9000

    @field_validator("dshot_speed", mode="after")
    @classmethod
    def validate_dshot_speed(cls, v: int) -> int:
        """Validate supported DShot speeds."""
        if v not in {150, 300, 600, 1200}:
            msg = "DShot speed must be one of 150, 300, 600, 1200"
            raise ValueError(msg)
        return v

    @field_validator("thruster_allocation", mode="before")
    @classmethod
    def validate_thruster_allocation(
        cls, v: list[list[float]]
    ) -> NumpyNDArray[np.float32]:
        """Validate and convert thruster allocation to numpy array."""
        return np.array(v, dtype=np.float32)

    @field_validator("nullspace_vectors", mode="before")
    @classmethod
    def validate_nullspace_vectors(
        cls,
        v: list[list[float]] | np.ndarray | None,
    ) -> list[np.ndarray]:
        """Validate and convert nullspace vectors to list of float32 arrays."""
        if v is None:
            return []
        if isinstance(v, np.ndarray):
            return [np.array(item, dtype=np.float32) for item in v]
        return [np.array(item, dtype=np.float32) for item in v]

    _config_path: ClassVar[Path] = Path(__file__).parents[1] / "config.json"

    @classmethod
    def load(cls) -> "RovConfig":
        """Load config from file with migration support."""
        if not cls._config_path.exists():
            default_config = cls()
            default_config.save()
            return default_config

        try:
            with cls._config_path.open() as f:
                raw = json.load(f)
        except (json.JSONDecodeError, ValueError):
            default_config = cls()
            default_config.save()
            return default_config

        stored_version = raw.get("firmwareVersion", "0.0.0")

        if compare_semver(stored_version, CURRENT_FIRMWARE_VERSION) > 0:
            return cls()

        raw = apply_migrations(raw)
        raw["firmwareVersion"] = CURRENT_FIRMWARE_VERSION

        return cls.model_validate(raw)

    def save(self) -> None:
        """Save config to file with current firmware version."""
        self.firmware_version = CURRENT_FIRMWARE_VERSION
        dir_path = self._config_path.parent
        tmp = Path(tempfile.mkstemp(dir=dir_path, suffix=".tmp")[1])
        try:
            with tmp.open("w") as f:
                _ = f.write(self.model_dump_json(by_alias=True, indent=2))
            tmp.replace(self._config_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


class PartialRovConfig(CamelCaseModel):
    """Partial ROV configuration for updates."""

    firmware_version: str | None = None
    mcu_firmware_version: str | None = None
    rov_name: str | None = None
    mcu_board: McuBoard | None = None
    thruster_protocol: ThrusterProtocol | None = None
    dshot_speed: int | None = None
    current_sensing_mode: CurrentSensingMode | None = None
    fluid_type: FluidType | None = None
    smoothing_factor: float | None = None
    thruster_pin_setup: ThrusterPinSetup | None = None
    thruster_allocation: (
        Annotated[np.ndarray, NDArraySchema((8, 8), np.float32)] | None
    ) = None
    nullspace_vectors: (
        list[Annotated[np.ndarray, NDArraySchema((8,), np.float32)]] | None
    ) = None
    regulator: Regulator | None = None
    direction_coefficients: DirectionCoefficients | None = None
    power: Power | None = None
    camera: Camera | None = None
    ip_address: str | None = None
    websocket_port: int | None = None

    @field_validator("thruster_allocation", mode="before")
    @classmethod
    def validate_thruster_allocation(
        cls, v: list[list[float]] | None
    ) -> NumpyNDArray[np.float32] | None:
        """Validate and convert thruster allocation to numpy array if present."""
        if v is None:
            return None
        return np.array(v, dtype=np.float32)

    @field_validator("nullspace_vectors", mode="before")
    @classmethod
    def validate_nullspace_vectors(
        cls,
        v: list[list[float]] | np.ndarray | None,
    ) -> list[np.ndarray] | None:
        """Validate and convert nullspace vectors to list of float32 arrays."""
        if v is None:
            return None
        if isinstance(v, np.ndarray):
            return [np.array(item, dtype=np.float32) for item in v]
        return [np.array(item, dtype=np.float32) for item in v]

    @field_validator("dshot_speed", mode="after")
    @classmethod
    def validate_optional_dshot_speed(cls, v: int | None) -> int | None:
        """Validate supported DShot speeds if present."""
        if v is None:
            return None
        if v not in {150, 300, 600, 1200}:
            msg = "DShot speed must be one of 150, 300, 600, 1200"
            raise ValueError(msg)
        return v


ThrusterTest = int


class RegulatorSuggestions(CamelCaseModel):
    """Suggestions for regulator tuning."""

    pitch: AxisConfig
    roll: AxisConfig
    yaw: AxisConfig
    depth: AxisConfig
