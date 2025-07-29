from typing import List, Literal, TypedDict


class IMUData(TypedDict):
    acceleration: float
    gyroscope: float
    temperature: float


class PressureData(TypedDict):
    pressure: float
    temperature: float
    depth: float


class RegulatorData(TypedDict):
    pitch: float
    roll: float
    desiredPitch: float
    desiredRoll: float


class ThrusterPinSetup(TypedDict):
    identifiers: List[int]
    spinDirections: List[int]


class PIDParams(TypedDict):
    kp: float
    ki: float
    kd: float


class RegulatorConfig(TypedDict):
    turnSpeed: float
    pitch: PIDParams
    roll: PIDParams
    depth: PIDParams


class DirectionCoefficients(TypedDict):
    horizontal: float
    strafe: float
    vertical: float
    pitch: float
    yaw: float
    roll: float


class PowerConfig(TypedDict):
    userMaxPower: float
    regulatorMaxPower: float
    batteryMinVoltage: float
    batteryMaxVoltage: float


class ROVConfig(TypedDict):
    fluidType: Literal["saltwater", "freshwater"]
    thrusterPinSetup: ThrusterPinSetup
    thrusterAllocation: List[List[int]]
    regulator: RegulatorConfig
    directionCoefficients: DirectionCoefficients
    power: PowerConfig


class Cancel(TypedDict):
    command: str
    payload: dict[str, object]
