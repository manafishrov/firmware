"""Configuration models for the ROV firmware."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray as NumpyNDArray
from numpydantic import NDArray, Shape
from pydantic import field_validator

from .base import CamelCaseModel


class MicrocontrollerFirmwareVariant(StrEnum):
    """Enum for microcontroller firmware variants."""

    PWM = "pwm"
    DSHOT = "dshot"


class FluidType(StrEnum):
    """Enum for fluid types."""

    FRESHWATER = "freshWater"
    SALTWATER = "saltWater"


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


class DirectionCoefficients(CamelCaseModel):
    """Direction coefficients for movement."""

    surge: float
    sway: float
    heave: float


class Power(CamelCaseModel):
    """Power configuration."""

    user_max_power: int
    regulator_max_power: int
    battery_min_voltage: float
    battery_max_voltage: float


class RovConfig(CamelCaseModel):
    """Main ROV configuration."""

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
        pitch=AxisConfig(kp=2, ki=0, kd=0.1, rate=1.0),
        roll=AxisConfig(kp=1, ki=0, kd=0.1, rate=1.0),
        yaw=AxisConfig(kp=3, ki=0, kd=0, rate=1.0),
        depth=AxisConfig(kp=0.5, ki=0, kd=0.1, rate=1.0),
    )
    direction_coefficients: DirectionCoefficients = DirectionCoefficients(
        surge=1,
        sway=1,
        heave=1,
    )
    power: Power = Power(
        user_max_power=30,
        regulator_max_power=30,
        battery_min_voltage=14,
        battery_max_voltage=21.5,
    )

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
        """Load config from file."""
        if not cls._config_path.exists():
            default_config = cls()
            default_config.save()
        with cls._config_path.open() as f:
            return cls.model_validate_json(f.read())

    def save(self) -> None:
        """Save config to file."""
        with self._config_path.open("w") as f:
            _ = f.write(self.model_dump_json(by_alias=True, indent=2))


ThrusterTest = int

FirmwareVersion = str


class RegulatorSuggestions(CamelCaseModel):
    """Suggestions for regulator tuning."""

    pitch: AxisConfig
    roll: AxisConfig
    depth: AxisConfig
