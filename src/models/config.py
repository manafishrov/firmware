"""Configuration models for the ROV firmware."""

from enum import Enum
from pathlib import Path

import numpy as np
from numpydantic import NDArray, Shape

from .base import CamelCaseModel


class MicrocontrollerFirmwareVariant(str, Enum):
    """Enum for microcontroller firmware variants."""

    PWM = "pwm"
    DSHOT = "dshot"


class FluidType(str, Enum):
    """Enum for fluid types."""

    FRESHWATER = "freshwater"
    SALTWATER = "saltwater"


class ThrusterPinSetup(CamelCaseModel):
    """Model for thruster pin setup."""

    identifiers: NDArray[Shape["8"], np.int8]  # pyright: ignore[reportGeneralTypeIssues]
    spin_directions: NDArray[Shape["8"], np.int8]  # pyright: ignore[reportGeneralTypeIssues]


class RegulatorPID(CamelCaseModel):
    """PID parameters for regulator."""

    kp: float
    ki: float
    kd: float


class Regulator(CamelCaseModel):
    """Regulator configuration."""

    turn_speed: int
    pitch: RegulatorPID
    roll: RegulatorPID
    depth: RegulatorPID


class DirectionCoefficients(CamelCaseModel):
    """Direction coefficients for movement."""

    surge: float
    sway: float
    heave: float
    pitch: float
    yaw: float
    roll: float


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
    thruster_pin_setup: ThrusterPinSetup = ThrusterPinSetup(
        identifiers=np.array([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int8),
        spin_directions=np.array(
            [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32
        ),
    )
    thruster_allocation: NDArray[Shape["8, 8"], np.float32] = np.array(  # pyright: ignore[reportInvalidTypeForm]
        (
            (1, 1, 0, 0, 0, 0, -1, -1),
            (1, -1, 0, 0, 0, 0, -1, 1),
            (0, 0, 1, 1, 1, 1, 0, 0),
            (0, 0, 1, 1, -1, -1, 0, 0),
            (-1, 1, 0, 0, 0, 0, 1, -1),
            (0, 0, 1, -1, 1, -1, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0, 0, 0, 0),
        )
    )
    regulator: Regulator = Regulator(
        turn_speed=40,
        pitch=RegulatorPID(kp=5, ki=0.5, kd=1),
        roll=RegulatorPID(kp=1.5, ki=0.1, kd=0.4),
        depth=RegulatorPID(kp=0, ki=0.05, kd=0.1),
    )
    direction_coefficients: DirectionCoefficients = DirectionCoefficients(
        surge=0.8,
        sway=0.35,
        heave=0.5,
        pitch=0.4,
        yaw=0.3,
        roll=0.8,
    )
    power: Power = Power(
        user_max_power=30,
        regulator_max_power=30,
        battery_min_voltage=9.6,
        battery_max_voltage=12.6,
    )

    _config_path: Path = Path(__file__).parent / "config.json"

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

    pitch: RegulatorPID
    roll: RegulatorPID
    depth: RegulatorPID
