from .base import CamelCaseModel

class RovTelemetry(CamelCaseModel):
    pitch: float
    roll: float
    desired_pitch: float
    desired_roll: float
    depth: float
    temperature: float
    thruster_erpms: tuple[int, int, int, int, int, int, int, int]


