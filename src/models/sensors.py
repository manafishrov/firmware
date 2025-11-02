"""Sensor data models for the ROV firmware."""

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel


class EscData(BaseModel):
    """Model for ESC data."""

    erpm: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    current_ca: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    voltage_cv: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    temperature: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]


class ImuData(BaseModel):
    """Model for IMU data."""

    acceleration: NDArray[np.float64] = np.array([0.0, 0.0, 0.0])
    gyroscope: NDArray[np.float64] = np.array([0.0, 0.0, 0.0])
    temperature: float = 0.0


class PressureData(BaseModel):
    """Model for pressure sensor data."""

    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
