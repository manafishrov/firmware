"""Sensor data models for the ROV firmware."""

import numpy as np

from pydantic import BaseModel


EscTuple = tuple[int, int, int, int, int, int, int, int]


class EscData(BaseModel):
    """Model for ESC data."""

    erpm: EscTuple
    current_ca: EscTuple
    voltage_cv: EscTuple
    temperature: EscTuple


class ImuData(BaseModel):
    """Model for IMU data."""

    acceleration: np.ndarray = np.array([0.0, 0.0, 0.0])
    gyroscope: np.ndarray = np.array([0.0, 0.0, 0.0])
    temperature: float = 0.0


class PressureData(BaseModel):
    """Model for pressure sensor data."""

    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
