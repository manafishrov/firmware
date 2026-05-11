"""Thruster data models for the ROV firmware."""

from typing import Annotated

import numpy as np
from numpydantic import NDArraySchema

from .base import CamelCaseModel


class ThrusterData(CamelCaseModel):
    """Model for thruster data."""

    direction_vector: Annotated[np.ndarray, NDArraySchema((8,), np.float32)] | None = (
        np.zeros(8)
    )
    work_indicator_percentage: int = 0
    last_direction_time: float = 0.0
    test_thruster: int | None = None
    test_start_time: float = 0.0
    last_remaining: int = 10
