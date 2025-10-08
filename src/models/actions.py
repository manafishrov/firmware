from .base import CamelCaseModel
from pydantic import field_validator
import numpy as np


class DirectionVector(CamelCaseModel):
    values: np.ndarray

    @field_validator("values", mode="before")
    @classmethod
    def to_array(cls, v):
        return np.array(v) if isinstance(v, (list, tuple)) else v


CustomAction = str
