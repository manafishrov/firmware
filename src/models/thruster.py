import numpy as np
from numpy.typing import NDArray

from .base import CamelCaseModel


class ThrusterData(CamelCaseModel):
    direction_vector: NDArray[np.float64] | None = np.zeros(8)
    last_direction_time: float = 0.0
    test_thruster: int | None = None
    test_start_time: float = 0.0
    last_remaining: int = 10
