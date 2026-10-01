"""Validate shared reading values at the firmware/app boundary."""

import math
from typing import cast

import numpy as np
from pydantic import JsonValue, TypeAdapter

from .models import ValueType


MAX_ARRAY_LENGTH = 4096
_JSON = TypeAdapter(JsonValue)


def normalize_value(value: object, value_type: ValueType) -> JsonValue:
    """Normalize numpy values and reject mismatched/non-finite samples."""
    if isinstance(value, np.ndarray):
        value = np.asarray(value).tolist()
    elif isinstance(value, np.generic):
        value = value.item()
    checks = {
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
        "number": type(value) in (float, int),
        "numberArray": isinstance(value, list)
        and len(value) <= MAX_ARRAY_LENGTH
        and all(type(item) in (float, int) for item in value),
        "json": True,
    }
    if not checks[value_type]:
        msg = f"Expected {value_type}, received {type(value).__name__}"
        raise ValueError(msg)
    result = _JSON.validate_python(value)
    _check_finite(result)
    return cast(JsonValue, result)


def _check_finite(value: JsonValue) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        msg = "Values must be finite"
        raise ValueError(msg)
    if isinstance(value, list):
        for child in value:
            _check_finite(child)
    elif isinstance(value, dict):
        for child in value.values():
            _check_finite(child)
