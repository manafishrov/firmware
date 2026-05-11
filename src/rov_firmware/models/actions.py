"""Data models for actions in the ROV firmware."""

from typing import Annotated

import numpy as np
from numpy.typing import NDArray as NumpyNDArray
from numpydantic import NDArraySchema
from pydantic import RootModel, model_validator


class DirectionVector(
    RootModel[Annotated[np.ndarray, NDArraySchema((8,), np.float32)]]
):
    """A direction vector for ROV movement."""

    @model_validator(mode="before")
    @classmethod
    def validate_root(cls, v: list[float]) -> NumpyNDArray[np.float32]:
        """Validate and convert direction vector to numpy array."""
        return np.array(v, dtype=np.float32)


CustomAction = str
