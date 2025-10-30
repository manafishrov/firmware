"""Base models and utilities for the ROV firmware."""

from pydantic import BaseModel, ConfigDict


def to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase.

    Args:
        snake_str: The snake_case string.

    Returns:
        The camelCase string.
    """
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class CamelCaseModel(BaseModel):
    """Base model with camel case aliasing."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
