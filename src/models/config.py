import os
from enum import Enum
from .base import CamelCaseModel


class MicrocontrollerFirmwareVariant(str, Enum):
    PWM = "pwm"
    DSHOT = "dshot"


class FluidType(str, Enum):
    FRESHWATER = "freshwater"
    SALTWATER = "saltwater"


class ThrusterPinSetup(CamelCaseModel):
    identifiers: tuple[int, int, int, int, int, int, int, int]
    spin_directions: tuple[int, int, int, int, int, int, int, int]


class RegulatorPID(CamelCaseModel):
    kp: float
    ki: float
    kd: float


class Regulator(CamelCaseModel):
    turn_speed: int
    pitch: RegulatorPID
    roll: RegulatorPID
    depth: RegulatorPID


class DirectionCoefficients(CamelCaseModel):
    horizontal: float
    strafe: float
    vertical: float
    pitch: float
    yaw: float
    roll: float


class Power(CamelCaseModel):
    user_max_power: int
    regulator_max_power: int
    battery_min_voltage: float
    battery_max_voltage: float


class RovConfig(CamelCaseModel):
    microcontroller_firmware_variant: MicrocontrollerFirmwareVariant = (
        MicrocontrollerFirmwareVariant.DSHOT
    )
    fluid_type: FluidType = FluidType.SALTWATER
    thruster_pin_setup: ThrusterPinSetup = ThrusterPinSetup(
        identifiers=(0, 1, 2, 3, 4, 5, 6, 7),
        spin_directions=(1, 1, 1, 1, 1, 1, 1, 1),
    )
    thruster_allocation: tuple[
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
        tuple[int, int, int, int, int, int, int, int],
    ] = (
        (1, 1, 0, 0, 0, 0, -1, -1),
        (1, -1, 0, 0, 0, 0, -1, 1),
        (0, 0, 1, 1, 1, 1, 0, 0),
        (0, 0, 1, 1, -1, -1, 0, 0),
        (-1, 1, 0, 0, 0, 0, 1, -1),
        (0, 0, 1, -1, 1, -1, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
    )
    regulator: Regulator = Regulator(
        turn_speed=40,
        pitch=RegulatorPID(kp=5, ki=0.5, kd=1),
        roll=RegulatorPID(kp=1.5, ki=0.1, kd=0.4),
        depth=RegulatorPID(kp=0, ki=0.05, kd=0.1),
    )
    direction_coefficients: DirectionCoefficients = DirectionCoefficients(
        horizontal=0.8,
        strafe=0.35,
        vertical=0.5,
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

    _config_path = os.path.join(os.path.dirname(__file__), "config.json")

    @classmethod
    def load(cls):
        if not os.path.exists(cls._config_path):
            default_config = cls()
            default_config.save()
        return cls.parse_file(cls._config_path)

    def save(self):
        with open(self._config_path, "w") as f:
            f.write(self.json(by_alias=True, indent=2))
