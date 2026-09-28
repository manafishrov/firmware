"""Correlated V1 management API over the existing WebSocket envelope."""

from typing import Any, Literal

from pydantic import Field

from ..models.base import CamelCaseModel


class RequestPayload(CamelCaseModel):
    """One bounded, versioned management or action operation."""

    version: Literal[1]
    request_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class CapabilityRequest(CamelCaseModel):
    """The single entry point for built-in and extension capabilities."""

    type: Literal["capabilityRequest"] = "capabilityRequest"
    payload: RequestPayload


class CapabilityResponse(CamelCaseModel):
    """Correlated success or actionable error response."""

    type: Literal["capabilityResponse"] = "capabilityResponse"
    payload: dict[str, Any]


class CapabilityCatalog(CamelCaseModel):
    """Discovery and initial values after connection or definition changes."""

    type: Literal["capabilityCatalog"] = "capabilityCatalog"
    payload: dict[str, Any]


class CapabilitySamples(CamelCaseModel):
    """Typed event stream shared by all producers."""

    type: Literal["capabilitySamples"] = "capabilitySamples"
    payload: dict[str, Any]
