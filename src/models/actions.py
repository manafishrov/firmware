from .base import CamelCaseModel
from pydantic import validator
import numpy as np


class DirectionVector(CamelCaseModel):
    __root__: np.ndarray

    @validator("__root__", pre=True)
    @classmethod
    def to_array(cls, v):
        return np.array(v) if isinstance(v, (list, tuple)) else v


CustomAction = str
