"""Sensor data models for the ROV firmware."""

from pydantic import BaseModel


class ImuData(BaseModel):
    """Model for IMU data."""

    acceleration: float = 0.0
    gyroscope: float = 0.0
    temperature: float = 0.0


class PressureData(BaseModel):
    """Model for pressure sensor data."""

    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
