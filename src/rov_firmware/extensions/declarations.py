"""Typed Python declarations that generate the shared capability catalogue."""

from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
import inspect
import keyword
from types import FunctionType
from typing import Literal, cast, get_origin, get_type_hints

import numpy as np
from pydantic import ConfigDict, JsonValue, TypeAdapter

from .models import Action, Manifest, Reading as ReadingDefinition
from .sdk import Context


type ActionFunction = Callable[[Context, JsonValue], Awaitable[None]]
type BackgroundFunction = Callable[[Context], Awaitable[None]]


class Trigger(StrEnum):
    """Supported operator activation modes."""

    ONCE = "once"
    HOLD = "hold"
    TOGGLE = "toggle"


class Widget(StrEnum):
    """Suggested display; operators choose size and placement in Appearance."""

    TEXT = "text"
    STATUS = "status"
    WARNING = "warning"
    PING = "ping"
    BAR = "bar"


def _value_type(
    value_type: object,
) -> Literal["boolean", "number", "string", "numberArray"]:
    if value_type is bool:
        return "boolean"
    if value_type in (int, float):
        return "number"
    if value_type is str:
        return "string"
    if (
        value_type == list[float]
        or value_type is np.ndarray
        or get_origin(value_type) is np.ndarray
    ):
        return "numberArray"
    msg = "Use bool, int, float, str, list[float], or a NumPy array type for readings"
    raise TypeError(msg)


def _check_identifier(identifier: str) -> None:
    if not identifier.isidentifier() or keyword.iskeyword(identifier):
        msg = f"{identifier!r} must be a Python identifier, not a keyword"
        raise ValueError(msg)


class Reading[T]:
    """A typed publication target owned by one loaded script."""

    def __init__(self, definition: ReadingDefinition, value_type: type[T]) -> None:
        """Create an unbound reading; only the firmware binds its context."""
        self.definition = definition
        self._adapter = TypeAdapter(
            value_type, config=ConfigDict(arbitrary_types_allowed=True)
        )
        self._context: Context | None = None

    async def publish(self, value: T | None) -> None:
        """Publish an event, or None when unavailable; reject mismatched values."""
        if self._context is None:
            msg = "Readings can only publish from an enabled custom action"
            raise RuntimeError(msg)
        validated = (
            None if value is None else self._adapter.validate_python(value, strict=True)
        )
        await self._context._publish_reading(self.definition.id, validated)


class Script:
    """Declare one script, its typed readings, and its callable actions."""

    def __init__(
        self, identifier: str, *, name: str | None = None, description: str = ""
    ) -> None:
        """Give the script its stable namespace and optional display text."""
        self._definition = Manifest(
            sdk_version=1,
            id=identifier,
            name=name or identifier.replace("_", " ").capitalize(),
            description=description,
        )
        self._readings: list[Reading[object]] = []
        self._actions: dict[str, ActionFunction] = {}
        self._background: BackgroundFunction | None = None
        self._sealed = False

    def _require_editable(self, identifier: str) -> None:
        if self._sealed:
            msg = "Declare readings and actions at module level, before the script is loaded"
            raise RuntimeError(msg)
        _check_identifier(identifier)
        if identifier in self._actions or any(
            item.definition.id == identifier for item in self._readings
        ):
            msg = f"Duplicate reading or action ID: {identifier}"
            raise ValueError(msg)

    def reading[T](  # noqa: PLR0913 - named metadata keeps typed SDK declarations direct
        self,
        identifier: str,
        value_type: type[T],
        *,
        name: str | None = None,
        unit: str | None = None,
        widget: Widget | None = None,
        stale_after: float | None = None,
    ) -> Reading[T]:
        """Declare a value once; retain its Python type when publishing."""
        self._require_editable(identifier)
        definition = ReadingDefinition(
            id=identifier,
            name=name or identifier.replace("_", " ").capitalize(),
            value_type=_value_type(value_type),
            unit=unit,
            widget=widget,
            stale_after_ms=None if stale_after is None else stale_after * 1000,
        )
        reading = Reading(definition, value_type)
        self._readings.append(cast(Reading[object], reading))
        return reading

    def action[F: Callable[..., Awaitable[None]]](
        self,
        *,
        name: str | None = None,
        identifier: str | None = None,
        modes: Sequence[Trigger] = (Trigger.ONCE,),
        mode: Trigger = Trigger.ONCE,
        interval_ms: int = 250,
    ) -> Callable[[F], F]:
        """Register the decorated async function without changing its signature."""

        def register(function: F) -> F:
            if not isinstance(function, FunctionType):
                msg = "Decorate an async function with script.action"
                raise TypeError(msg)
            local_id = identifier or function.__name__
            self._require_editable(local_id)
            if local_id == "background":
                msg = "background is reserved for the background task"
                raise ValueError(msg)
            parameters = _parameters(function)
            input_type = _action_input_type(function, parameters)
            definition = Action(
                id=local_id,
                name=name or local_id.replace("_", " ").capitalize(),
                input_type=input_type,
                modes=[trigger.value for trigger in modes],
                mode=mode.value,
                interval_ms=interval_ms,
            )
            self._definition.actions.append(definition)
            self._actions[local_id] = _handler(function, parameters)
            return function

        return register

    def background(
        self, *, continue_on_disconnect: bool = False
    ) -> Callable[[BackgroundFunction], BackgroundFunction]:
        """Register one cooperative background task, with explicit unattended opt-in."""

        def register(function: BackgroundFunction) -> BackgroundFunction:
            if self._sealed or self._background is not None:
                msg = "Declare exactly one background task at module level"
                raise ValueError(msg)
            if len(_parameters(function)) != 1:
                msg = "A background task accepts only ctx"
                raise TypeError(msg)
            self._background = function
            self._definition.background = True
            self._definition.continue_on_disconnect = continue_on_disconnect
            return function

        return register

    def _seal(self) -> Manifest:
        self._sealed = True
        self._definition.readings = [reading.definition for reading in self._readings]
        self._definition = Manifest.model_validate(self._definition.model_dump())
        return self._definition

    def _bind(self, context: Context) -> None:
        for reading in self._readings:
            reading._context = context


def _parameters(function: Callable[..., Awaitable[None]]) -> list[inspect.Parameter]:
    parameters = list(inspect.signature(function).parameters.values())
    if (
        not inspect.iscoroutinefunction(function)
        or len(parameters) not in (1, 2)
        or any(
            parameter.kind
            not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            for parameter in parameters
        )
    ):
        msg = "An action must be async def function(ctx), optionally with a typed second argument"
        raise TypeError(msg)
    return parameters


def _action_input_type(
    function: Callable[..., Awaitable[None]], parameters: list[inspect.Parameter]
) -> Literal["none", "boolean", "number", "string", "numberArray"]:
    if len(parameters) == 1:
        return "none"
    annotation = get_type_hints(function).get(parameters[1].name)
    if annotation is np.ndarray or get_origin(annotation) is np.ndarray:
        msg = "Use list[float] for numeric array action inputs"
        raise TypeError(msg)
    return _value_type(annotation)


def _handler(
    function: Callable[..., Awaitable[None]], parameters: list[inspect.Parameter]
) -> ActionFunction:
    adapter = (
        TypeAdapter(get_type_hints(function)[parameters[1].name])
        if len(parameters) > 1
        else None
    )

    async def invoke(context: Context, value: JsonValue) -> None:
        if adapter is None:
            await function(context)
        else:
            await function(context, adapter.validate_python(value, strict=True))

    return invoke
