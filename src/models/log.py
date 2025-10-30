from enum import Enum

from .base import CamelCaseModel


class LogLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LogOrigin(str, Enum):
    FIRMWARE = "firmware"
    BACKEND = "backend"
    FRONTEND = "frontend"


class LogEntry(CamelCaseModel):
    origin: LogOrigin
    level: LogLevel
    message: str
