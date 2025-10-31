"""ESC data models for the ROV firmware."""

from .base import CamelCaseModel


EscTuple = tuple[int, int, int, int, int, int, int, int]


class EscData(CamelCaseModel):
    """Model for ESC data."""

    erpm: EscTuple
    current_ca: EscTuple
    voltage_cv: EscTuple
    temperature: EscTuple
