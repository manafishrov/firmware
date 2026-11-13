"""Full-resolution photos from the video camera, handed over to the operator's app.

The camera stream process (``camera/manafish_camerad.cpp``) owns the camera.
A request on its socket switches the sensor to its full 4056x3040 mode for a
single frame and straight back to video, so the live video only freezes for
the mode switch. The process then saves a JPEG and a RAW .dng in the
background.

Finished photos wait in an outbox on the SD card only until the app has
downloaded them: the app lists the outbox over HTTP, downloads each file and
then deletes the photo. Downloads use their own connection, so they never
delay control messages or telemetry, and the ROV paces them to
TRANSFER_BYTES_PER_SECOND so they leave room for the live video.
"""

import asyncio
from contextlib import suppress
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import cast, override

from .log import log_error, log_info, log_warn


PHOTO_SOCKET = Path("/run/manafish-camera/photo.sock")
TRANSFER_PORT = 9001
TRANSFER_BYTES_PER_SECOND = 5_000_000
TRANSFER_CHUNK_BYTES = 64 * 1024
# A JPEG + RAW pair is about 28 MB; never fill the SD card the firmware runs from.
MIN_FREE_BYTES = 300 * 1024 * 1024
CONNECT_TIMEOUT = 2.0
CAPTURE_TIMEOUT = 10.0
SAVE_TIMEOUT = 60.0

_PHOTO_ID = re.compile(r"photo_[0-9A-Za-z_-]{1,80}")
_PHOTO_FILE = re.compile(rf"(?P<id>{_PHOTO_ID.pattern})\.(?P<extension>jpg|dng)")


class PhotoError(RuntimeError):
    """A photo could not be taken or saved."""


class _Outbox:
    """Photos the camera is still writing, or failed to write, by photo ID."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._saving: set[str] = set()
        self._failed: dict[str, str] = {}
        # Keep save watchers referenced until they finish.
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, photo_id: str, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._saving.add(photo_id)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def finish(self, photo_id: str, error: str | None) -> None:
        with self._lock:
            self._saving.discard(photo_id)
            if error is not None:
                self._failed[photo_id] = error

    def forget(self, photo_id: str) -> None:
        with self._lock:
            self._failed.pop(photo_id, None)

    def status(self) -> tuple[list[str], dict[str, str]]:
        with self._lock:
            return sorted(self._saving), dict(self._failed)


_outbox = _Outbox()


def outbox_directory() -> Path:
    """SD card storage for photos the app has not downloaded yet."""
    root = Path(
        os.environ.get(
            "MANAFISH_DATA_DIR", str(Path.home() / ".local" / "share" / "manafish")
        )
    )
    return root / "photo_outbox"


def _new_photo_base(directory: Path) -> Path:
    """Name photos by local time, adding a counter if two land in one second."""
    stem = f"photo_{datetime.now().astimezone():%Y-%m-%d_%H-%M-%S}"
    base = directory / stem
    counter = 2
    while base.with_suffix(".jpg").exists() or base.with_suffix(".dng").exists():
        base = directory / f"{stem}_{counter}"
        counter += 1
    return base


async def _open_camera() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_unix_connection(str(PHOTO_SOCKET))


async def _read_reply(reader: asyncio.StreamReader, timeout: float) -> str:
    line = (await asyncio.wait_for(reader.readline(), timeout)).decode().strip()
    if not line:
        msg = "The camera stopped before the photo was saved"
        raise PhotoError(msg)
    if line.startswith("error "):
        detail = line.removeprefix("error ")
        raise PhotoError(detail[:1].upper() + detail[1:])
    return line


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with suppress(OSError):
        await writer.wait_closed()


async def _await_saved(
    photo_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Move a captured photo from saving to ready (or failed) in the outbox."""
    error = None
    try:
        reply = await _read_reply(reader, SAVE_TIMEOUT)
        if not reply.startswith("saved "):
            error = f"Unexpected camera reply: {reply}"
    except TimeoutError:
        error = "The camera did not finish saving the photo"
    except PhotoError as failure:
        error = str(failure)
    finally:
        await _close(writer)
        _outbox.finish(photo_id, error)
    if error is None:
        log_info(f"Photo {photo_id} is ready for the app")
    else:
        log_error(f"Photo {photo_id} could not be saved: {error}")


async def capture_photo() -> str:
    """Take one full-resolution photo and return its ID once the frame is taken.

    The video runs again when this returns; the files are written in the
    background and appear in the outbox shortly after.

    Raises:
        PhotoError: The camera is not streaming, is busy, or failed.
    """
    directory = outbox_directory()
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    free = (await asyncio.to_thread(shutil.disk_usage, directory)).free
    if free < MIN_FREE_BYTES:
        msg = f"Only {free // (1024 * 1024)} MB free on the ROV's SD card"
        raise PhotoError(msg)
    base = _new_photo_base(directory)
    try:
        reader, writer = await asyncio.wait_for(_open_camera(), CONNECT_TIMEOUT)
    except (OSError, TimeoutError) as error:
        # go2rtc only runs the camera while someone watches the video.
        msg = "The camera is not streaming; open the video first"
        raise PhotoError(msg) from error
    try:
        writer.write(f"{base}\n".encode())
        await writer.drain()
        reply = await _read_reply(reader, CAPTURE_TIMEOUT)
        if reply != "captured":
            msg = f"Unexpected camera reply: {reply}"
            raise PhotoError(msg)
    except TimeoutError as error:
        await _close(writer)
        msg = "The camera did not answer"
        raise PhotoError(msg) from error
    except BaseException:
        await _close(writer)
        raise
    photo_id = base.name
    _outbox.start(photo_id, asyncio.create_task(_await_saved(photo_id, reader, writer)))
    return photo_id


class _Pacer:
    """Share one byte rate between every download, so bursts never stack up."""

    def __init__(self, bytes_per_second: float) -> None:
        self._lock = threading.Lock()
        self._rate = bytes_per_second
        self._next = time.monotonic()

    def wait(self, size: int) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + size / self._rate
        if start > now:
            time.sleep(start - now)


def _ready_photos(directory: Path) -> list[dict[str, object]]:
    """Photos whose files are complete; the camera renames the JPEG last."""
    photos = []
    for jpeg in sorted(directory.glob("photo_*.jpg")):
        if _PHOTO_ID.fullmatch(jpeg.stem) is None:
            continue
        files = [
            {"name": path.name, "size": path.stat().st_size}
            for path in (jpeg, jpeg.with_suffix(".dng"))
            if path.exists()
        ]
        photos.append({"id": jpeg.stem, "files": files})
    return photos


class PhotoTransferHandler(BaseHTTPRequestHandler):
    """List, download and delete outbox photos for the operator's app.

    GET /photos lists ready, saving and failed photos, GET /photos/<file>
    downloads one file at the paced rate, and DELETE /photos/<id> removes a
    photo once the app has stored it.
    """

    @property
    def _photos(self) -> "PhotoTransferServer":
        return cast(PhotoTransferServer, self.server)

    def _send_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _list(self) -> None:
        saving, failed = _outbox.status()
        self._send_json(
            {
                "ready": _ready_photos(self._photos.directory),
                "saving": saving,
                "failed": [
                    {"id": key, "error": value} for key, value in failed.items()
                ],
            }
        )

    def _download(self, name: str) -> None:
        if _PHOTO_FILE.fullmatch(name) is None:
            self.send_error(404)
            return
        try:
            file = (self._photos.directory / name).open("rb")
        except FileNotFoundError:
            self.send_error(404)
            return
        with file:
            size = os.fstat(file.fileno()).st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            while chunk := file.read(TRANSFER_CHUNK_BYTES):
                self._photos.pacer.wait(len(chunk))
                self.wfile.write(chunk)

    def do_GET(self) -> None:
        """List the outbox or download one photo file."""
        if self.path == "/photos":
            self._list()
        elif self.path.startswith("/photos/"):
            with suppress(ConnectionError):
                self._download(self.path.removeprefix("/photos/"))
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        """Remove a downloaded or failed photo; deleting twice is harmless."""
        photo_id = self.path.removeprefix("/photos/")
        if not self.path.startswith("/photos/") or not _PHOTO_ID.fullmatch(photo_id):
            self.send_error(404)
            return
        for extension in (".jpg", ".dng"):
            (self._photos.directory / f"{photo_id}{extension}").unlink(missing_ok=True)
        _outbox.forget(photo_id)
        self.send_response(204)
        self.end_headers()

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Keep transfers out of the firmware log."""


class PhotoTransferServer(ThreadingHTTPServer):
    """Serve one outbox directory, with every download sharing one pace."""

    def __init__(self, port: int, directory: Path) -> None:
        """Bind on every interface; the app connects over the tether."""
        self.directory = directory
        self.pacer = _Pacer(TRANSFER_BYTES_PER_SECOND)
        super().__init__(("", port), PhotoTransferHandler)


def start_photo_transfer(port: int = TRANSFER_PORT) -> PhotoTransferServer | None:
    """Serve the outbox on a background thread; photos still work if this fails."""
    directory = outbox_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Leftovers from a camera that was killed mid-save.
        for partial in directory.glob("*.part"):
            partial.unlink(missing_ok=True)
        server = PhotoTransferServer(port, directory)
    except OSError as error:
        log_warn(f"Photo transfer unavailable: {error}")
        return None
    threading.Thread(
        target=server.serve_forever, name="photo_transfer", daemon=True
    ).start()
    return server
