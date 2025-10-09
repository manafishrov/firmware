from pydantic import BaseModel


class ImuData(BaseModel):
    acceleration: float = 0.0
    gyroscope: float = 0.0
    temperature: float = 0.0
    measured_at: float = 0.0


class PressureData(BaseModel):
    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
    measured_at: float = 0.0
