"""Full-resolution photos from the video camera, and a page to download them.

The camera stream process (``camera/manafish_camerad.cpp``) owns the camera.
A request on its socket switches the sensor to its full 4056x3040 mode for a
single frame and straight back to video, so the live video only freezes for
the mode switch. The process then saves a JPEG and a RAW .dng in the
background. Photos are stored on the SD card and served for download over
HTTP, so no app changes are needed to get them onto a computer.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import threading
from typing import override
from urllib.parse import quote

from .log import log_info, log_warn
from .models.toast import ToastContent
from .toast import toast_error, toast_loading, toast_success


PHOTO_SOCKET = Path("/run/manafish-camera/photo.sock")
PHOTO_PAGE_PORT = 8080
# A JPEG + RAW pair is about 30 MB; never fill the SD card the firmware runs from.
MIN_FREE_BYTES = 300 * 1024 * 1024
CONNECT_TIMEOUT = 2.0
CAPTURE_TIMEOUT = 10.0
SAVE_TIMEOUT = 60.0
_TOAST_ID = "photo"


class PhotoError(RuntimeError):
    """A photo could not be taken or saved."""


def photo_directory() -> Path:
    """Persistent photo storage next to custom actions and CSV logs."""
    root = Path(
        os.environ.get(
            "MANAFISH_DATA_DIR", str(Path.home() / ".local" / "share" / "manafish")
        )
    )
    return root / "photos"


def photo_page_url(ip_address: str) -> str:
    """Address of the download page as seen from the operator's computer."""
    return f"http://{ip_address}:{PHOTO_PAGE_PORT}"


def _new_photo_base(directory: Path) -> Path:
    """Name photos by local time, adding a counter if two land in one second."""
    stem = f"photo_{datetime.now().astimezone():%Y-%m-%d_%H-%M-%S}"
    base = directory / stem
    counter = 2
    while base.with_suffix(".jpg").exists():
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


async def capture_photo(on_captured: Callable[[], None] | None = None) -> Path:
    """Take one full-resolution photo and return the JPEG; the .dng sits next to it.

    Args:
        on_captured: Called once the frame is taken and the video runs again,
            before the files are written.

    Raises:
        PhotoError: The camera is not streaming, is busy, or failed.
    """
    directory = photo_directory()
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    free = (await asyncio.to_thread(shutil.disk_usage, directory)).free
    if free < MIN_FREE_BYTES:
        msg = f"Only {free // (1024 * 1024)} MB free on the SD card"
        raise PhotoError(msg)
    base = _new_photo_base(directory)
    try:
        reader, writer = await asyncio.wait_for(_open_camera(), CONNECT_TIMEOUT)
    except (OSError, TimeoutError) as error:
        # go2rtc only runs the camera while someone watches the video.
        msg = "The camera is not streaming; open the video in the app"
        raise PhotoError(msg) from error
    try:
        writer.write(f"{base}\n".encode())
        await writer.drain()
        if (reply := await _read_reply(reader, CAPTURE_TIMEOUT)) != "captured":
            msg = f"Unexpected camera reply: {reply}"
            raise PhotoError(msg)
        if on_captured is not None:
            on_captured()
        reply = await _read_reply(reader, SAVE_TIMEOUT)
    except TimeoutError as error:
        msg = "The camera did not answer"
        raise PhotoError(msg) from error
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
    if not reply.startswith("saved "):
        msg = f"Unexpected camera reply: {reply}"
        raise PhotoError(msg)
    return Path(reply.removeprefix("saved "))


async def take_photo(page_url: str) -> Path:
    """Take a photo and keep the operator informed through one updating toast."""

    def notify(message: str) -> None:
        toast_loading(_TOAST_ID, ToastContent(message=message), None)

    notify("Taking photo...")
    try:
        jpeg = await capture_photo(on_captured=lambda: notify("Saving photo..."))
    except asyncio.CancelledError:
        toast_error(_TOAST_ID, ToastContent(message="Photo cancelled"), None)
        raise
    except PhotoError as error:
        toast_error(
            _TOAST_ID,
            ToastContent(message="Could not take photo", description=str(error)),
            None,
        )
        raise
    log_info(f"Saved photo {jpeg}")
    toast_success(
        _TOAST_ID,
        ToastContent(
            message="Photo saved",
            description=f"{jpeg.name} + RAW. Download at {page_url}",
        ),
        None,
    )
    return jpeg


def _size(path: Path) -> str:
    return f"{path.stat().st_size / (1024 * 1024):.1f} MB"


class PhotoPageHandler(SimpleHTTPRequestHandler):
    """Serve the photo folder with a newest-first download page."""

    @override
    def list_directory(self, path: str | os.PathLike[str]) -> None:
        rows = []
        for photo in sorted(Path(path).glob("*.jpg"), reverse=True):
            links = [f'<a href="{quote(photo.name)}">View</a>']
            for file in (photo, photo.with_suffix(".dng")):
                if file.exists():
                    links.append(
                        f'<a href="{quote(file.name)}" download>'
                        f"{file.suffix[1:].upper()} ({_size(file)})</a>"
                    )
            rows.append(f"<li><b>{escape(photo.stem)}</b> {' | '.join(links)}</li>")
        body = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Manafish photos</title>"
            "<style>body{font-family:sans-serif;margin:2em}li{margin:.6em 0}</style>"
            "<h1>Manafish photos</h1>"
            f"<ul>{''.join(rows) or '<li>No photos yet</li>'}</ul>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Keep downloads out of the firmware log."""


def start_photo_page(port: int = PHOTO_PAGE_PORT) -> ThreadingHTTPServer | None:
    """Serve photos on a background thread; photos still work if this fails."""
    directory = photo_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        server = ThreadingHTTPServer(
            ("", port), partial(PhotoPageHandler, directory=str(directory))
        )
    except OSError as error:
        log_warn(f"Photo download page unavailable: {error}")
        return None
    threading.Thread(
        target=server.serve_forever, name="photo_page", daemon=True
    ).start()
    return server
