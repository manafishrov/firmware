"""Python helpers for trusted extensions sharing the live firmware state."""

import asyncio
from collections.abc import Callable
from enum import StrEnum

import numpy as np
from pydantic import JsonValue, TypeAdapter

from ..log import log_info
from ..rov_state import RovState
from ..toast import ToastContent, ToastVariant, toast_content
from .csv_store import CsvStore


_CSV_ROW = TypeAdapter(list[JsonValue])


class NotificationLevel(StrEnum):
    """Visual severity for plain-text custom action notifications."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warn"
    ERROR = "error"


class Context:
    """Expose the actual RovState instance and extension-local publishing helpers."""

    def __init__(
        self,
        rov: RovState,
        publish: Callable[[str, object], None],
        csv: CsvStore,
        identifier: str,
    ) -> None:
        """Keep the original objects and types; no state serialization or proxy."""
        self.rov: RovState = rov
        self._publish = publish
        self._csv = csv
        self._identifier = identifier
        self._closed = False

    def close(self) -> None:
        """Prevent stopped extensions from publishing or starting new CSV writes."""
        self._closed = True

    def _require_active(self) -> None:
        if self._closed:
            msg = "Extension has stopped"
            raise RuntimeError(msg)

    async def _publish_reading(self, identifier: str, value: object) -> None:
        """Publish a declared local reading, retaining repeated event identity."""
        self._require_active()
        self._publish(identifier, value)
        await asyncio.sleep(0)

    async def log_csv(self, values: object, filename: str) -> None:
        """Append a list or one-dimensional numpy array as one CSV row."""
        self._require_active()
        if isinstance(values, np.ndarray):
            values = np.asarray(values).tolist()
        if not isinstance(values, list):
            msg = "CSV values must be a list or one-dimensional numpy array"
            raise ValueError(msg)
        # Complete accepted writes before cancellation finishes: Stop must not
        # return while a detached thread can still append to the recording.
        write = asyncio.create_task(
            asyncio.to_thread(
                self._csv.append, _CSV_ROW.validate_python(values), filename
            )
        )
        cancelled = False
        while not write.done():
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                cancelled = True
        write.result()
        if cancelled:
            raise asyncio.CancelledError

    async def notify(
        self,
        message: str,
        *,
        level: NotificationLevel = NotificationLevel.INFO,
        description: str | None = None,
        key: str | None = None,
    ) -> None:
        """Show plain text through the shared toast system; a key updates one alert."""
        self._require_active()
        if not message.strip():
            msg = "A notification message must not be empty"
            raise ValueError(msg)
        toast_content(
            identifier=None
            if key is None
            else f"custom-action:{self._identifier}:{key}",
            variant=ToastVariant(level.value),
            content=ToastContent(message=message, description=description),
            action=None,
        )
        await asyncio.sleep(0)

    async def log(self, message: str) -> None:
        """Send an extension-labelled message to the app's firmware debug log."""
        log_info(f"Extension {self._identifier}: {message}")
        await asyncio.sleep(0)
