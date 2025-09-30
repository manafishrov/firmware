from pydantic import BaseModel
from typing import List
import os


def to_camel(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class CamelCaseModel(BaseModel):
    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True


class ThrusterPinSetup(CamelCaseModel):
    identifiers: List[int]
    spin_directions: List[int]


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


class ROVConfig(CamelCaseModel):
    microcontroller_firmware_variant: str
    fluid_type: str
    thruster_pin_setup: ThrusterPinSetup
    thruster_allocation: List[List[int]]
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
