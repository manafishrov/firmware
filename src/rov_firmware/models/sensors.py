"""Sensor data models for the ROV firmware."""

from typing import Annotated

import numpy as np
from numpydantic import NDArraySchema
from pydantic import BaseModel


class McuData(BaseModel):
    """Model for MCU telemetry data."""

    erpm: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    current: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    voltage: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    temperature: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    signal_quality: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class ImuData(BaseModel):
    """Model for IMU data."""

    acceleration: Annotated[np.ndarray, NDArraySchema((3,), np.float32)] = np.array(
        [0.0, 0.0, 0.0], dtype=np.float32
    )
    gyroscope: Annotated[np.ndarray, NDArraySchema((3,), np.float32)] = np.array(
        [0.0, 0.0, 0.0], dtype=np.float32
    )
    temperature: float = 0.0


class PressureData(BaseModel):
    """Model for pressure sensor data."""

    pressure: float = 0.0
    temperature: float = 0.0
    depth: float = 0.0
