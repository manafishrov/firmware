"""Read-only Python sources for desktop analysis; never import user scripts."""

import base64
from functools import lru_cache
import gzip
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import threading
import tomllib
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


CHUNK_BYTES = 65536
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
_BUILD_LOCK = threading.Lock()


class SourceBundle(BaseModel):
    """An immutable, content-addressed snapshot of installed Python definitions."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    revision: str
    data: bytes

    def describe(self) -> dict[str, str | int]:
        """Describe the bytes before the desktop downloads them."""
        return {"revision": self.revision, "size": len(self.data)}

    def read(self, revision: str, offset: object) -> dict[str, str | int | bool]:
        """Return one bounded chunk of the specified immutable snapshot."""
        if revision != self.revision:
            msg = "SDK definitions changed; start the download again"
            raise ValueError(msg)
        if type(offset) is not int or not 0 <= offset <= len(self.data):
            msg = "SDK offset must be an integer within the archive"
            raise ValueError(msg)
        chunk = self.data[offset : offset + CHUNK_BYTES]
        end = offset + len(chunk)
        return {
            "data": base64.b64encode(chunk).decode(),
            "nextOffset": end,
            "eof": end == len(self.data),
        }


def _distributions() -> list[metadata.Distribution]:
    """Follow installed runtime requirements, excluding development extras."""
    project = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if project.is_file():
        dependencies = tomllib.loads(project.read_text())["project"]["dependencies"]
        pending = [
            match[0]
            for requirement in dependencies
            if (match := re.match(r"[A-Za-z0-9_.-]+", requirement))
        ]
    else:
        pending = ["manafish"]
    seen: set[str] = set()
    result = []
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        result.append(distribution)
        for requirement in distribution.requires or []:
            if "extra ==" in requirement or "extra==" in requirement:
                continue
            match = re.match(r"[A-Za-z0-9_.-]+", requirement)
            if match:
                pending.append(match[0])
    return result


def _add_file(files: dict[str, str], path: Path, name: str) -> None:
    if path.suffix not in {".py", ".pyi"} or any(
        part in {"tests", "test", "__pycache__"} or part.startswith(".")
        for part in Path(name).parts
    ):
        return
    if path.is_file():
        files[name] = path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _build() -> SourceBundle:
    files: dict[str, str] = {}
    for distribution in _distributions():
        for entry in distribution.files or []:
            name = entry.as_posix()
            if ".." not in entry.parts and not entry.is_absolute():
                _add_file(files, Path(str(distribution.locate_file(entry))), name)
    # Editable installs have no package sources in their wheel file list.
    root = Path(__file__).resolve().parents[2]
    for package in ("rov_firmware", "manafish_sdk"):
        for path in (root / package).rglob("*.py"):
            _add_file(files, path, path.relative_to(root).as_posix())
    raw = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_SOURCE_BYTES:
        msg = "Installed SDK definitions exceed the 64 MiB analysis limit"
        raise ValueError(msg)
    data = gzip.compress(raw, mtime=0)
    if len(data) > MAX_ARCHIVE_BYTES:
        msg = "Compressed SDK definitions exceed the 16 MiB transfer limit"
        raise ValueError(msg)
    return SourceBundle(revision=hashlib.sha256(data).hexdigest(), data=data)


def source_bundle() -> SourceBundle:
    """Build once off-loop, serializing simultaneous requests without duplicate work."""
    with _BUILD_LOCK:
        return _build()
