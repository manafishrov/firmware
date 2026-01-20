"""Log data models for the ROV firmware."""

from enum import StrEnum

from .base import CamelCaseModel


class LogLevel(StrEnum):
    """Enum for log levels."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LogOrigin(StrEnum):
    """Enum for log origins."""

    FIRMWARE = "firmware"
    BACKEND = "backend"
    FRONTEND = "frontend"


class LogEntry(CamelCaseModel):
    """Model for log entries."""

    origin: LogOrigin
    level: LogLevel
    message: str
