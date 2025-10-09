from pydantic import RootModel, field_validator
import numpy as np


class DirectionVector(RootModel[np.ndarray]):
    @field_validator("root", mode="before")
    @classmethod
    def to_float_array(cls, v):
        return np.array(v, dtype=float) if isinstance(v, (list, tuple)) else v


CustomAction = str
