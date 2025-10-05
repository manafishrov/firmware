from .base import CamelCaseModel


class EscData(CamelCaseModel):
    erpm: tuple[int, int, int, int, int, int, int, int]
    current_ca: tuple[int, int, int, int, int, int, int, int]
    voltage_cv: tuple[int, int, int, int, int, int, int, int]
    temperature: tuple[int, int, int, int, int, int, int, int]
