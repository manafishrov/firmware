"""ESC data models for the ROV firmware."""

from .base import CamelCaseModel


class EscData(CamelCaseModel):
    """Model for ESC data."""

    erpm: tuple[int, int, int, int, int, int, int, int]
    current_ca: tuple[int, int, int, int, int, int, int, int]
    voltage_cv: tuple[int, int, int, int, int, int, int, int]
    temperature: tuple[int, int, int, int, int, int, int, int]
