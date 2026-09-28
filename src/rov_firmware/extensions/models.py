"""Versioned extension declarations and capability wire models."""

import time
from typing import ClassVar, Literal

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    computed_field,
    model_validator,
)

from ..models.base import CamelCaseModel


ValueType = Literal["boolean", "number", "string", "numberArray", "json"]
Mode = Literal["once", "hold", "toggle"]


class Declaration(CamelCaseModel):
    """Reject misspelled or unsupported declaration fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        alias_generator=CamelCaseModel.model_config["alias_generator"],
        populate_by_name=True,
        extra="forbid",
    )


class Reading(Declaration):
    """A discoverable typed reading."""

    id: str = Field(pattern=r"^[a-z][a-zA-Z0-9_.-]{0,95}$")
    name: str = Field(min_length=1, max_length=100)
    value_type: ValueType
    extension_id: str | None = None
    unit: str | None = None
    widget: str | None = None
    stale_after_ms: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class Action(Declaration):
    """An invokable capability with persistent trigger preferences."""

    id: str = Field(pattern=r"^[a-z][a-zA-Z0-9_.-]{0,95}$")
    name: str = Field(min_length=1, max_length=100)
    input_type: Literal["none", "boolean", "number", "string", "numberArray"] = "none"
    extension_id: str | None = None
    modes: list[Mode] = Field(default=["once"], min_length=1)
    mode: Mode = "once"
    interval_ms: int = Field(default=250, ge=50, le=3_600_000)

    @model_validator(mode="after")
    def check_mode(self) -> "Action":
        """Ensure the selected activation mode is supported."""
        if self.mode not in self.modes:
            msg = "Selected mode must be listed in modes"
            raise ValueError(msg)
        return self


class Manifest(Declaration):
    """Catalogue metadata generated from a script's typed SDK declarations."""

    sdk_version: Literal[1]
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    readings: list[Reading] = Field(default_factory=list, max_length=64)
    actions: list[Action] = Field(default_factory=list, max_length=32)
    background: bool = False
    continue_on_disconnect: bool = False

    @model_validator(mode="after")
    def check_ids(self) -> "Manifest":
        """Keep extension IDs stable, namespaced, and unambiguous."""
        if self.id == "rov":
            msg = "The rov namespace is reserved"
            raise ValueError(msg)
        ids = [item.id for item in [*self.readings, *self.actions]]
        if len(ids) != len(set(ids)):
            msg = "Reading and action IDs must be unique"
            raise ValueError(msg)
        for item in [*self.readings, *self.actions]:
            if "." in item.id or "-" in item.id:
                msg = "Manifest IDs must be local Python identifiers"
                raise ValueError(msg)
            item.extension_id = self.id
        return self


class Sample(CamelCaseModel):
    """An event; sequence changes even when the value is unchanged."""

    id: str
    value: JsonValue
    sequence: int
    timestamp: float
    _recorded_at: float = PrivateAttr(default_factory=time.monotonic)

    @computed_field(alias="ageMs")
    @property
    def age_ms(self) -> float:
        """Include source age at serialization, even after queuing or reconnection."""
        return max(0, (time.monotonic() - self._recorded_at) * 1000)


class ExtensionInfo(CamelCaseModel):
    """Persisted extension identity and current runtime health."""

    id: str
    name: str
    description: str
    enabled: bool = False
    status: Literal["stopped", "running", "error"] = "stopped"
    error: str | None = None


class TriggerPreferences(Declaration):
    """Validated trigger settings persisted independently of source updates."""

    mode: Mode
    interval_ms: int = Field(ge=50, le=3_600_000, strict=True)


class ExtensionPreferences(Declaration):
    """Persisted enablement and per-action trigger overrides."""

    enabled: bool = Field(default=False, strict=True)
    actions: dict[str, TriggerPreferences] = Field(default_factory=dict)
