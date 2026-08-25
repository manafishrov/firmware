"""Durable recovery journal for interrupted ESC firmware transactions."""

import json
import os
from pathlib import Path
import tempfile
from typing import Any


_RECOVERY_JOURNAL_PATH = (
    Path.home() / ".local" / "state" / "manafish" / "esc-firmware-update.json"
)


def recovery_journal_exists() -> bool:
    """Return whether an earlier ESC transaction may have reached COMMIT."""
    return _RECOVERY_JOURNAL_PATH.exists()


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def mark_recovery_required(target_version: str | None) -> None:
    """Durably record that normal motor output must stay blocked."""
    path = _RECOVERY_JOURNAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "phase": "commit",
        "targetVersion": target_version,
    }
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def clear_recovery_required() -> None:
    """Durably clear the recovery journal after a verified safe outcome."""
    path = _RECOVERY_JOURNAL_PATH
    if not path.exists():
        return
    path.unlink()
    _fsync_directory(path.parent)
