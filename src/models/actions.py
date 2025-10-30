"""Data models for actions in the ROV firmware."""

import numpy as np
from pydantic import RootModel, field_validator


class DirectionVector(RootModel[np.ndarray]):
    """A direction vector for ROV movement."""

    @field_validator("root", mode="before")
    @classmethod
    def to_float_array(cls, v: list[float]) -> None:
        """Convert to float array."""
        return np.array(v, dtype=float) if isinstance(v, (list, tuple)) else v


CustomAction = str
