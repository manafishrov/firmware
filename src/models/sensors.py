"""Sensor data models for the ROV firmware."""

import numpy as np
from numpydantic import NDArray, Shape
from pydantic import BaseModel


class EscData(BaseModel):
    """Model for ESC data."""

    erpm: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    current_ca: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    voltage_cv: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    temperature: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]


class ImuData(BaseModel):
    """Model for IMU data."""

    acceleration: NDArray[Shape["3"], np.float32] = np.array([0.0, 0.0, 0.0])  # pyright: ignore[reportGeneralTypeIssues]
    gyroscope: NDArray[Shape["3"], np.float32] = np.array([0.0, 0.0, 0.0])  # pyright: ignore[reportGeneralTypeIssues]
    temperature: float = 0.0


class PressureData(BaseModel):
    """Model for pressure sensor data."""

    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
