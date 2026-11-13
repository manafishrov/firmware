import asyncio
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

import pytest

from rov_firmware import photo
from rov_firmware.custom_actions import builtins
from rov_firmware.custom_actions.csv_store import CsvStore
from rov_firmware.custom_actions.sdk import Context


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MANAFISH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(photo, "_outbox", photo._Outbox())
    return tmp_path


class FakeCamera:
    """Speaks manafish-camerad's photo protocol over TCP instead of a Unix socket."""

    def __init__(self, replies=None, save_delay=0.0):
        self.replies = replies
        self.save_delay = save_delay
        self.requests = []
        self.server = None

    async def handle(self, reader, writer):
        base = Path((await reader.readline()).decode().strip())
        self.requests.append(base)
        for reply in self.replies or ["captured", f"saved {base}.jpg"]:
            if reply.startswith("saved "):
                await asyncio.sleep(self.save_delay)
                base.with_suffix(".dng").write_bytes(b"raw")
                base.with_suffix(".jpg").write_bytes(b"jpeg")
            writer.write(f"{reply}\n".encode())
            await writer.drain()
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc):
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    def connect(self):
        assert self.server is not None
        port = self.server.sockets[0].getsockname()[1]
        return asyncio.open_connection("127.0.0.1", port)


def run_with_camera(monkeypatch, camera, scenario):
    async def main():
        async with camera:
            monkeypatch.setattr(photo, "_open_camera", camera.connect)
            return await scenario()

    return asyncio.run(main())


async def settle():
    """Let the background save watchers finish."""
    async with asyncio.timeout(2):
        while photo._outbox.status()[0]:
            await asyncio.sleep(0.01)


def test_capture_returns_once_taken_and_saves_into_the_outbox(monkeypatch, data_dir):
    camera = FakeCamera(save_delay=0.2)

    async def scenario():
        photo_id = await photo.capture_photo()
        saving, _ = photo._outbox.status()
        await settle()
        return photo_id, saving

    photo_id, saving_after_capture = run_with_camera(monkeypatch, camera, scenario)

    assert saving_after_capture == [photo_id]
    outbox = data_dir / "photo_outbox"
    assert camera.requests == [outbox / photo_id]
    assert (outbox / f"{photo_id}.jpg").read_bytes() == b"jpeg"
    assert photo._outbox.status() == ([], {})


def test_photos_taken_in_the_same_second_get_unique_names(monkeypatch):
    async def two_photos():
        first = await photo.capture_photo()
        await settle()
        return first, await photo.capture_photo()

    first, second = run_with_camera(monkeypatch, FakeCamera(), two_photos)

    assert first != second


def test_camera_error_before_capture_is_raised(monkeypatch):
    camera = FakeCamera(replies=["error a photo is already being taken"])

    with pytest.raises(photo.PhotoError, match=r"^A photo is already being taken$"):
        run_with_camera(monkeypatch, camera, photo.capture_photo)
    assert photo._outbox.status() == ([], {})


def test_save_failure_is_reported_in_the_outbox(monkeypatch):
    camera = FakeCamera(replies=["captured", "error failed to write photo"])

    async def scenario():
        photo_id = await photo.capture_photo()
        await settle()
        return photo_id

    photo_id = run_with_camera(monkeypatch, camera, scenario)

    assert photo._outbox.status() == ([], {photo_id: "Failed to write photo"})


def test_missing_stream_is_reported(monkeypatch):
    async def no_camera():
        raise FileNotFoundError(photo.PHOTO_SOCKET)

    monkeypatch.setattr(photo, "_open_camera", no_camera)

    with pytest.raises(photo.PhotoError, match="not streaming"):
        asyncio.run(photo.capture_photo())


def test_full_sd_card_is_refused_before_contacting_the_camera(monkeypatch):
    monkeypatch.setattr(
        photo.shutil, "disk_usage", lambda _path: type("Usage", (), {"free": 0})
    )
    camera = FakeCamera()

    with pytest.raises(photo.PhotoError, match="0 MB free"):
        run_with_camera(monkeypatch, camera, photo.capture_photo)
    assert camera.requests == []


@pytest.fixture
def transfer(data_dir):
    outbox = data_dir / "photo_outbox"
    outbox.mkdir()
    (outbox / "photo_1.jpg").write_bytes(b"jpeg")
    (outbox / "photo_1.dng").write_bytes(b"raw-data")
    (outbox / "photo_2.dng.part").write_bytes(b"half")
    server = photo.start_photo_transfer(port=0)
    assert server is not None
    yield server, outbox
    server.shutdown()
    server.server_close()


def http(server, method, path):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    request = urllib.request.Request(url, method=method)  # noqa: S310
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        return response.status, response.read()


def test_transfer_lists_downloads_and_deletes_photos(transfer):
    server, outbox = transfer
    photo._outbox._saving.add("photo_3")
    photo._outbox.finish("photo_4", "Failed to write photo")

    status, body = http(server, "GET", "/photos")
    assert status == 200
    assert json.loads(body) == {
        "ready": [
            {
                "id": "photo_1",
                "files": [
                    {"name": "photo_1.jpg", "size": 4},
                    {"name": "photo_1.dng", "size": 8},
                ],
            }
        ],
        "saving": ["photo_3"],
        "failed": [{"id": "photo_4", "error": "Failed to write photo"}],
    }
    # A camera killed mid-save leaves partial files; startup removes them.
    assert not (outbox / "photo_2.dng.part").exists()

    assert http(server, "GET", "/photos/photo_1.dng") == (200, b"raw-data")
    assert http(server, "DELETE", "/photos/photo_1")[0] == 204
    assert http(server, "DELETE", "/photos/photo_4")[0] == 204
    assert not list(outbox.iterdir())
    assert json.loads(http(server, "GET", "/photos")[1])["failed"] == []


@pytest.mark.parametrize(
    "path", ["/photos/../secret.jpg", "/photos/photo_1.txt", "/photos/other.jpg", "/"]
)
def test_transfer_only_serves_outbox_photos(transfer, path):
    server, _ = transfer
    with pytest.raises(urllib.error.HTTPError, match="404"):
        http(server, "GET", path)


def test_downloads_are_paced(transfer):
    server, outbox = transfer
    size = 4 * photo.TRANSFER_CHUNK_BYTES
    (outbox / "photo_5.jpg").write_bytes(bytes(size))
    # Pace this server at 1 MB/s so the 256 KiB download takes ~0.25 s.
    server.pacer = photo._Pacer(1_000_000)

    start = time.monotonic()
    status, body = http(server, "GET", "/photos/photo_5.jpg")

    assert (status, len(body)) == (200, size)
    assert time.monotonic() - start >= 0.18


def test_builtin_action_takes_a_photo(monkeypatch, rov_state):
    calls = []

    async def capture():
        calls.append(True)
        return "photo_1"

    monkeypatch.setattr(builtins, "capture_photo", capture)
    assert "rov.photo.capture" in {action.id for action in builtins.actions()}

    asyncio.run(builtins.invoke(rov_state, "rov.photo.capture", None))

    assert calls == [True]


def test_custom_actions_can_take_photos(monkeypatch, rov_state, tmp_path):
    calls = []

    async def capture():
        calls.append(True)
        return "photo_1"

    monkeypatch.setattr("rov_firmware.custom_actions.sdk.capture_photo", capture)
    context = Context(rov_state, lambda *_: None, CsvStore(tmp_path / "csv"), "camera")

    asyncio.run(context.take_photo())

    assert calls == [True]
