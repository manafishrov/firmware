"""Sensor data models for the ROV firmware."""

from typing import Annotated

import numpy as np
from numpydantic import NDArraySchema
from pydantic import BaseModel


class McuData(BaseModel):
    """Model for MCU telemetry data."""

    erpm: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    current: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    current_valid: list[bool] = [False, False, False, False, False, False, False, False]
    board_current_ma: list[int | None] = [None, None]
    board_baseline_ma: list[int | None] = [None, None]
    board_current_updated_at: list[float] = [0.0, 0.0]
    board_baseline_updated_at: list[float] = [0.0, 0.0]
    voltage: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    temperature: list[int] = [0, 0, 0, 0, 0, 0, 0, 0]
    signal_quality: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    signal_quality_valid: list[bool] = [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]

    def clear_board_current(self) -> None:
        """Invalidate auto-zero reports across USB sessions and MCU resets."""
        self.board_current_ma = [None, None]
        self.board_baseline_ma = [None, None]
        self.board_current_updated_at = [0.0, 0.0]
        self.board_baseline_updated_at = [0.0, 0.0]


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
    depth_change: float = 0.0
