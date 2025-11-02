"""Data models for actions in the ROV firmware."""

import numpy as np
from numpydantic import NDArray, Shape
from pydantic import RootModel


class DirectionVector(RootModel[NDArray[Shape["6"], np.float32]]):
    """A direction vector for ROV movement."""


CustomAction = str
