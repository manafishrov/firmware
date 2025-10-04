import os
from enum import Enum
from .base_model import CamelCaseModel


class MicrocontrollerFirmwareVariant(str, Enum):
    PWM = "pwm"
    DSHOT = "dshot"


class FluidType(str, Enum):
    FRESHWATER = "freshwater"
    SALTWATER = "saltwater"


class ThrusterPinSetup(CamelCaseModel):
    identifiers: tuple[int, int, int, int, int, int, int, int] = (
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    )
    spin_directions: tuple[int, int, int, int, int, int, int, int] = (
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )


class RegulatorPID(CamelCaseModel):
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0


class Regulator(CamelCaseModel):
    turn_speed: int = 40
    pitch: RegulatorPID = RegulatorPID()
    roll: RegulatorPID = RegulatorPID()
    depth: RegulatorPID = RegulatorPID()


class DirectionCoefficients(CamelCaseModel):
    horizontal: float = 0.0
    strafe: float = 0.0
    vertical: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0


class Power(CamelCaseModel):
    user_max_power: int = 30
    regulator_max_power: int = 30
    battery_min_voltage: float = 9.6
    battery_max_voltage: float = 12.6


class ROVConfig(CamelCaseModel):
    microcontroller_firmware_variant: MicrocontrollerFirmwareVariant
    fluid_type: FluidType
    thruster_pin_setup: ThrusterPinSetup
    thruster_allocation: tuple[
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
    ]
    regulator: Regulator
    direction_coefficients: DirectionCoefficients
    power: Power

    _config_path = os.path.join(os.path.dirname(__file__), "config.json")

    @classmethod
    def load(cls):
        return cls.parse_file(cls._config_path)

    def save(self):
        with open(self._config_path, "w") as f:
            f.write(self.json(by_alias=True, indent=2))
