"""Data models for actions in the ROV firmware."""

import numpy as np
from numpy.typing import NDArray
from pydantic import RootModel, field_validator


class DirectionVector(RootModel[NDArray[np.float64]]):
    """A direction vector for ROV movement."""

    @field_validator("root", mode="before")
    @classmethod
    def to_float_array(cls, v: list[float]) -> NDArray[np.float64]:
        """Convert to float array."""
        return np.array(v, dtype=float)


CustomAction = str
