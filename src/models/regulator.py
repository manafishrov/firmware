from pydantic import BaseModel


class RegulatorData(BaseModel):
    pitch: float = 0.0
    roll: float = 0.0
    desired_pitch: float = 0.0
    desired_roll: float = 0.0
    desired_depth: float = 0.0
    auto_tuning_active: bool = False
    auto_tuning_start_time: float = 0.0
