"""Bounded CSV storage with consistent download snapshots."""

import base64
import csv
import io
from pathlib import Path
import re
import shutil
import threading
import uuid

from pydantic import JsonValue

from .values import normalize_value


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_CHUNK_BYTES = 64 * 1024
MAX_SNAPSHOTS = 4


class CsvStore:
    """Serialize append/delete/snapshot operations independently of control."""

    def __init__(self, directory: Path) -> None:
        """Create storage and an ephemeral snapshot area."""
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.snapshots = directory / ".snapshots"
        shutil.rmtree(self.snapshots, ignore_errors=True)
        self.snapshots.mkdir()
        self._tokens: dict[str, Path] = {}
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}\.csv", name):
            msg = "Use a plain CSV filename, without directories"
            raise ValueError(msg)
        path = self.directory / name
        if path.is_symlink():
            msg = "Symbolic links are not CSV files"
            raise ValueError(msg)
        return path

    def append(self, values: list[JsonValue], name: str) -> None:
        """Append one consistent-width row; reject quotas and invalid cells."""
        if not values or any(isinstance(v, (dict, list)) for v in values):
            msg = "CSV rows require a nonempty list of scalar values"
            raise ValueError(msg)
        normalize_value(values, "json")
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerow(values)
        encoded = buffer.getvalue().encode()
        with self._lock:
            path = self._path(name)
            size = path.stat().st_size if path.exists() else 0
            if size:
                with path.open(newline="") as stream:
                    columns = len(next(csv.reader(stream)))
                if len(values) != columns:
                    msg = f"{name} expects {columns} columns"
                    raise ValueError(msg)
            total = sum(p.stat().st_size for p in self.directory.glob("*.csv"))
            if (
                size + len(encoded) > MAX_FILE_BYTES
                or total + len(encoded) > MAX_TOTAL_BYTES
            ):
                msg = "CSV storage quota reached; download and delete files"
                raise ValueError(msg)
            with path.open("ab") as stream:
                stream.write(encoded)

    def list(self) -> list[dict[str, JsonValue]]:
        """Count logical rows, including quoted multiline CSV cells."""
        with self._lock:
            result: list[dict[str, JsonValue]] = []
            for path in sorted(self.directory.glob("*.csv")):
                if path.is_symlink():
                    continue
                with path.open(newline="") as stream:
                    rows, columns = 0, 0
                    for row in csv.reader(stream):
                        rows += 1
                        columns = max(columns, len(row))
                result.append(
                    {
                        "name": path.name,
                        "rows": rows,
                        "columns": columns,
                        "size": path.stat().st_size,
                    }
                )
            return result

    def open(self, name: str) -> dict[str, JsonValue]:
        """Copy under the append lock so downloads never change underneath clients."""
        with self._lock:
            if len(self._tokens) >= MAX_SNAPSHOTS:
                msg = "Close an existing download before opening another"
                raise ValueError(msg)
            token = uuid.uuid4().hex
            destination = self.snapshots / token
            shutil.copyfile(self._path(name), destination)
            self._tokens[token] = destination
            return {"token": token, "size": destination.stat().st_size}

    def read(self, token: str, offset: int) -> dict[str, JsonValue]:
        """Read a bounded base64 chunk at an explicit byte offset."""
        with self._lock:
            path = self._tokens[token]
            if offset < 0 or offset > path.stat().st_size:
                msg = "Download offset is outside the snapshot"
                raise ValueError(msg)
            with path.open("rb") as stream:
                stream.seek(offset)
                data = stream.read(MAX_CHUNK_BYTES)
            position = offset + len(data)
            return {
                "data": base64.b64encode(data).decode(),
                "nextOffset": position,
                "eof": position == path.stat().st_size,
            }

    def close(self, token: str) -> None:
        """Release a download snapshot."""
        with self._lock:
            path = self._tokens.pop(token, None)
            if path is not None:
                path.unlink(missing_ok=True)

    def close_all(self) -> None:
        """Release downloads when their owning connection disappears."""
        for token in list(self._tokens):
            self.close(token)

    def delete(self, name: str) -> None:
        """Remove a file after the app has confirmed the operation."""
        with self._lock:
            self._path(name).unlink()
