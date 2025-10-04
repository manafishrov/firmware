from .base import CamelCaseModel


class RovStatus(CamelCaseModel):
    pitch_stabilization: bool
    roll_stabilization: bool
    depth_stabilization: bool
    battery_percentage: int
