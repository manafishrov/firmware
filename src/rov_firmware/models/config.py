"""Configuration models for the ROV firmware."""

from enum import StrEnum
import json
from pathlib import Path
import secrets
import tempfile
import tomllib
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray as NumpyNDArray
from numpydantic import NDArray, Shape
from pydantic import Field, field_validator

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

    # Example: migrate config when firmware_version < "1.0.0"
    # if compare_semver(firmware_version, "1.0.0") == -1:
    #     # Add migration logic here
    #     pass

    _ = firmware_version  # Placeholder until migrations are needed
    return raw


class MicrocontrollerFirmwareVariant(StrEnum):
    """Enum for microcontroller firmware variants."""

    PWM = "pwm"
    DSHOT = "dshot"


class FluidType(StrEnum):
    """Enum for fluid types."""

    FRESHWATER = "freshwater"
    SALTWATER = "saltwater"


class ThrusterPinSetup(CamelCaseModel):
    """Model for thruster pin setup."""

    identifiers: NDArray[Shape["8"], np.int8]  # ty: ignore[invalid-type-form]
    spin_directions: NDArray[Shape["8"], np.int8]  # ty: ignore[invalid-type-form]

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

    @field_validator("min_battery_voltage", "max_battery_voltage", mode="after")
    @classmethod
    def validate_battery_voltage(cls, v: float) -> float:
        """Validate that battery voltage is positive."""
        if v <= 0:
            msg = "Battery voltage must be positive"
            raise ValueError(msg)
        return v


class RovConfig(CamelCaseModel):
    """Main ROV configuration."""

    firmware_version: str = CURRENT_FIRMWARE_VERSION
    rov_name: str = Field(default_factory=_generate_rov_name)
    microcontroller_firmware_variant: MicrocontrollerFirmwareVariant = (
        MicrocontrollerFirmwareVariant.DSHOT
    )
    fluid_type: FluidType = FluidType.SALTWATER
    smoothing_factor: float = 0.0
    thruster_pin_setup: ThrusterPinSetup = ThrusterPinSetup(
        identifiers=np.array([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int8),
        spin_directions=np.array([1, 1, 1, 1, 1, 1, 1, 1], dtype=np.int8),
    )
    thruster_allocation: NDArray[Shape["8, 8"], np.float32] = np.array(  # ty: ignore[invalid-type-form]
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
    regulator: Regulator = Regulator(
        pitch=AxisConfig(kp=3, ki=2, kd=0.5, rate=100.0),
        roll=AxisConfig(kp=3, ki=2, kd=0.5, rate=100.0),
        yaw=AxisConfig(kp=3, ki=2, kd=0.5, rate=100.0),
        depth=AxisConfig(kp=2, ki=0.5, kd=0.1, rate=0.5),
        fpv_mode=False,
    )
    direction_coefficients: DirectionCoefficients = DirectionCoefficients(
        surge=1,
        sway=1,
        heave=1,
    )
    power: Power = Power(
        thrusters_limit=30,
        actions_limit=30,
        regulator_limit=30,
        min_battery_voltage=14,
        max_battery_voltage=21.5,
    )
    ip_address: str = "10.10.10.10"
    websocket_port: int = 9000

    @field_validator("thruster_allocation", mode="before")
    @classmethod
    def validate_thruster_allocation(
        cls, v: list[list[float]]
    ) -> NumpyNDArray[np.float32]:
        """Validate and convert thruster allocation to numpy array."""
        return np.array(v, dtype=np.float32)

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
    rov_name: str | None = None
    microcontroller_firmware_variant: MicrocontrollerFirmwareVariant | None = None
    fluid_type: FluidType | None = None
    smoothing_factor: float | None = None
    thruster_pin_setup: ThrusterPinSetup | None = None
    thruster_allocation: NDArray[Shape["8, 8"], np.float32] | None = None  # ty: ignore[invalid-type-form]
    regulator: Regulator | None = None
    direction_coefficients: DirectionCoefficients | None = None
    power: Power | None = None
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


ThrusterTest = int


class RegulatorSuggestions(CamelCaseModel):
    """Suggestions for regulator tuning."""

    pitch: AxisConfig
    roll: AxisConfig
    yaw: AxisConfig
    depth: AxisConfig
