import asyncio
from pathlib import Path
import urllib.request

import pytest

from rov_firmware import photo
from rov_firmware.custom_actions.runtime import CustomActionRuntime


EXAMPLE = Path(__file__).parents[1] / "examples/custom_actions/take_photo.py"


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MANAFISH_DATA_DIR", str(tmp_path))
    return tmp_path


class FakeCamera:
    """Speaks manafish-camerad's photo protocol over TCP instead of a Unix socket."""

    def __init__(self, replies=None):
        self.replies = replies
        self.requests = []
        self.server = None

    async def handle(self, reader, writer):
        base = (await reader.readline()).decode().strip()
        self.requests.append(base)
        replies = self.replies or [
            "captured",
            "saved " + str(Path(base).with_suffix(".jpg")),
        ]
        for reply in replies:
            if reply.startswith("saved "):
                Path(base).with_suffix(".jpg").write_bytes(b"jpeg")
                Path(base).with_suffix(".dng").write_bytes(b"raw")
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


def test_capture_saves_jpeg_and_raw(monkeypatch, data_dir):
    camera = FakeCamera()
    captured = []

    jpeg = run_with_camera(
        monkeypatch,
        camera,
        lambda: photo.capture_photo(on_captured=lambda: captured.append(True)),
    )

    assert captured == [True]
    assert jpeg.parent == data_dir / "photos"
    assert jpeg.name.startswith("photo_")
    assert jpeg.read_bytes() == b"jpeg"
    assert jpeg.with_suffix(".dng").exists()
    assert camera.requests == [str(jpeg.with_suffix(""))]


def test_photos_taken_in_the_same_second_get_unique_names(monkeypatch):
    camera = FakeCamera()

    async def two_photos():
        return [await photo.capture_photo(), await photo.capture_photo()]

    first, second = run_with_camera(monkeypatch, camera, two_photos)

    assert first != second


def test_camera_error_is_reported(monkeypatch):
    camera = FakeCamera(replies=["error failed to allocate buffers"])

    with pytest.raises(photo.PhotoError, match=r"^Failed to allocate buffers$"):
        run_with_camera(monkeypatch, camera, photo.capture_photo)


def test_camera_closing_early_is_reported(monkeypatch):
    camera = FakeCamera(replies=["captured"])

    with pytest.raises(photo.PhotoError, match="stopped before"):
        run_with_camera(monkeypatch, camera, photo.capture_photo)


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
def toasts(monkeypatch):
    sent = []
    for variant in ("loading", "success", "error"):
        monkeypatch.setattr(
            photo,
            f"toast_{variant}",
            lambda identifier, content, _action, variant=variant: sent.append(
                (variant, identifier, content.message)
            ),
        )
    return sent


def test_take_photo_updates_one_toast(monkeypatch, toasts):
    run_with_camera(
        monkeypatch, FakeCamera(), lambda: photo.take_photo("http://10.10.10.10:8080")
    )

    assert toasts == [
        ("loading", "photo", "Taking photo..."),
        ("loading", "photo", "Saving photo..."),
        ("success", "photo", "Photo saved"),
    ]


def test_take_photo_shows_failures(monkeypatch, toasts):
    camera = FakeCamera(replies=["error busy"])

    with pytest.raises(photo.PhotoError):
        run_with_camera(monkeypatch, camera, lambda: photo.take_photo("url"))
    assert toasts[-1] == ("error", "photo", "Could not take photo")


def test_photo_page_lists_and_serves_photos(data_dir):
    photos = data_dir / "photos"
    photos.mkdir()
    (photos / "photo_1.jpg").write_bytes(b"jpeg")
    (photos / "photo_1.dng").write_bytes(b"raw")
    (photos / "photo_2.jpg.part").write_bytes(b"half")
    server = photo.start_photo_page(port=0)
    assert server is not None

    def get(path):
        url = f"http://127.0.0.1:{server.server_address[1]}/{path}"
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return response.read()

    try:
        page = get("").decode()
        assert "photo_1" in page
        assert "photo_1.dng" in page
        assert "photo_2" not in page
        assert get("photo_1.jpg") == b"jpeg"
        assert get("photo_1.dng") == b"raw"
    finally:
        server.shutdown()
        server.server_close()


def test_photo_page_failure_does_not_stop_firmware(monkeypatch):
    def unavailable(*_args):
        msg = "address in use"
        raise OSError(msg)

    monkeypatch.setattr(photo, "ThreadingHTTPServer", unavailable)

    assert photo.start_photo_page() is None


def test_example_action_takes_a_photo(rov_state, tmp_path, monkeypatch):
    pages = []

    async def fake_take_photo(page_url):
        pages.append(page_url)
        return tmp_path / "photo.jpg"

    monkeypatch.setattr("rov_firmware.custom_actions.sdk.take_photo", fake_take_photo)
    runtime = CustomActionRuntime(rov_state, tmp_path)

    async def scenario():
        try:
            await runtime.install(EXAMPLE.read_text())
            await runtime.enable("photo", True)
            await runtime.invoke("photo.take_photo")
            async with asyncio.timeout(2):
                while "photo.take_photo" in runtime.running or not pages:
                    await asyncio.sleep(0.01)
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())

    assert pages == ["http://10.10.10.10:8080"]
