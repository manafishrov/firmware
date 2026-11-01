"""Record the ROV's built-in readings to CSV, like a flight recorder.

Installed disabled by default: enable it in Custom actions to start recording.
Recording continues without an app connection, so a lost connection is covered.
Bind "Toggle logging" to an action widget or keyboard/controller button to
pause/resume, and add "Logging" in Appearance to see whether it is recording.
Pausing is temporary: recording resumes after an app disconnect, script reload,
or ROV restart while enabled. Disable the custom action to stop recording.

Each start writes a new blackbox_<UTC time>.csv, including the restart after an
app disconnects, and a new file begins every FILE_DURATION_SECONDS or when the
current file reaches the per-file CSV limit. Download or delete recordings in
CSV logging. Edit COLUMNS to choose the logged readings.

When CSV storage is full, the oldest blackbox_*.csv recordings are permanently
deleted to make room, so download recordings you want to keep. Other CSV files
are never deleted; if they alone leave no room, logging stops with an error.
"""

import asyncio
from datetime import UTC, datetime
import time
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from manafish_sdk import Context, NotificationLevel, Script, Widget
from rov_firmware.custom_actions.builtins import READING_DEFINITIONS, values
from rov_firmware.custom_actions.csv_store import CsvQuotaError


LOG_INTERVAL_SECONDS = 0.1
FILE_DURATION_SECONDS = 3600
FILE_PREFIX = "blackbox_"
# Built-in reading IDs without the "rov." prefix; arrays get one column per item.
COLUMNS = (
    "depth",
    "desiredDepth",
    "pitch",
    "roll",
    "yaw",
    "desiredPitch",
    "desiredRoll",
    "desiredYaw",
    "waterTemperature",
    "electronicsTemperature",
    "batteryPercentage",
    "currentDraw",
    "workIndicatorPercentage",
    "thrusterRpms",
    "autoStabilization",
    "depthHold",
    "thrusterControlReady",
    "thrusterProtocolState",
    "piUndervoltage",
)

script = Script(
    "blackbox",
    name="Blackbox logging",
    description="Record built-in ROV readings to CSV, including while disconnected.",
)
logging_active = script.reading("logging", bool, name="Logging", widget=Widget.STATUS)
recording_file = script.reading("file", str, name="Blackbox file", widget=Widget.TEXT)


class RecorderState(BaseModel):
    """Track the current file; module state resets when the script reloads."""

    model_config: ClassVar[ConfigDict] = ConfigDict(validate_assignment=True)

    recording: bool = True
    filename: str | None = None
    file_started: float = 0.0


recorder = RecorderState()
# Serialize toggles and writes so a pause never races an in-flight row.
recorder_lock = asyncio.Lock()


def _snapshot(ctx: Context) -> tuple[list[str], list[object]]:
    """Return column names and values from the same readings the app shows."""
    readings = values(ctx.rov)
    names: list[str] = []
    cells: list[object] = []
    for key in COLUMNS:
        unit = READING_DEFINITIONS[key][2]
        suffix = f" ({unit})" if unit else ""
        value = readings[f"rov.{key}"]
        if isinstance(value, list):
            names += [f"{key} {index}{suffix}" for index in range(1, len(value) + 1)]
            cells += value
        else:
            names.append(f"{key}{suffix}")
            cells.append(value)
    return names, cells


async def _append(ctx: Context, row: list[object]) -> None:
    """Append to the current file, deleting the oldest recordings to make room."""
    filename = recorder.filename
    if filename is None:
        msg = "No blackbox file is open"
        raise RuntimeError(msg)
    await ctx.log_csv(row, filename, delete_oldest=FILE_PREFIX)


async def _start_file(ctx: Context, names: list[str], now: float) -> None:
    """Begin a new recording with its header."""
    started = datetime.now(UTC)
    # Milliseconds keep a quick restart from appending to the previous file.
    recorder.filename = (
        f"{FILE_PREFIX}{started:%Y%m%d-%H%M%S}-{started.microsecond // 1000:03d}.csv"
    )
    recorder.file_started = now
    await _append(ctx, ["time (UTC)", "elapsed (s)", *names])
    await recording_file.publish(recorder.filename)


async def write_row(ctx: Context) -> None:
    """Append one row, starting a new file with a header when needed."""
    now = time.monotonic()
    names, cells = _snapshot(ctx)
    if (
        recorder.filename is None
        or now - recorder.file_started >= FILE_DURATION_SECONDS
    ):
        await _start_file(ctx, names, now)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    elapsed = round(now - recorder.file_started, 3)
    try:
        await _append(ctx, [timestamp, elapsed, *cells])
    except CsvQuotaError:
        # The file is full, or room remains only once it is deleted: start anew.
        await _start_file(ctx, names, now)
        await _append(ctx, [timestamp, 0.0, *cells])


@script.action(name="Toggle logging")
async def toggle_logging(ctx: Context) -> None:
    """Pause/resume once per press; the background task owns the recording loop."""
    async with recorder_lock:
        recorder.recording = not recorder.recording
        await logging_active.publish(recorder.recording)
        await ctx.notify(
            "Blackbox logging resumed"
            if recorder.recording
            else "Blackbox logging paused",
            key="status",
        )


@script.background(continue_on_disconnect=True)
async def record(ctx: Context) -> None:
    """Start on enable and yield between rows so other firmware keeps running."""
    await logging_active.publish(recorder.recording)
    while True:
        async with recorder_lock:
            if recorder.recording:
                try:
                    await write_row(ctx)
                except ValueError as error:
                    # Storage failures stop the recording visibly, never silently.
                    await ctx.notify(
                        "Blackbox logging stopped",
                        level=NotificationLevel.ERROR,
                        description=str(error),
                        key="status",
                    )
                    msg = f"Failed to write {recorder.filename}: {error}"
                    raise RuntimeError(msg) from error
        await asyncio.sleep(LOG_INTERVAL_SECONDS)
