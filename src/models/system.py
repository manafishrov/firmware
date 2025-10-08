from pydantic import BaseModel


class SystemHealth(BaseModel):
    imu_ok: bool = False
    pressure_sensor_ok: bool = False
    microcontroller_ok: bool = False


class SystemStatus(BaseModel):
    pitch_stabilization: bool = False
    roll_stabilization: bool = False
    depth_stabilization: bool = False
