from .base import CamelCaseModel
from typing import Optional
from numpy.typing import NDArray
import numpy as np


class ThrusterData(CamelCaseModel):
    direction_vector: Optional[NDArray[np.float64]] = np.zeros(8)
    last_direction_time: float = 0.0
