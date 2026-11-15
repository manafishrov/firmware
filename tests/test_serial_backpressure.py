"""A Pico that stops reading USB must not freeze the firmware event loop."""

import asyncio
import contextlib
import os
import pty
import threading
import time

import pytest

from rov_firmware.serial import open_mcu_serial


@pytest.fixture
def unread_port():
    """A PTY whose far end never reads, like a Pico that stopped draining USB."""
    controller, device = pty.openpty()
    yield os.ttyname(device)
    os.close(device)
    os.close(controller)


def _fill(writer: asyncio.StreamWriter) -> None:
    """Fill the port until it stays full; the PTY frees space asynchronously."""
    fd = writer.transport.get_extra_info("serial").fd
    os.set_blocking(fd, False)
    for _ in range(100):
        written = 0
        with contextlib.suppress(BlockingIOError):
            while True:
                written += os.write(fd, bytes(1024))
        if written == 0:
            return
        time.sleep(0.02)
    pytest.fail("PTY never stayed full")


def _run_with_deadline(coroutine, seconds: float = 5.0):
    """Fail instead of hanging if the event loop spins inside a write."""
    result: list[object] = []
    thread = threading.Thread(
        target=lambda: result.append(asyncio.run(coroutine)), daemon=True
    )
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "serial write blocked the event loop"
    return result[0]


def test_write_to_full_port_times_out_without_blocking_the_loop(unread_port):
    async def scenario():
        _, writer = await open_mcu_serial(unread_port)
        _fill(writer)
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        beat = asyncio.create_task(heartbeat())
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.2):
                writer.write(bytes(34))
                await writer.drain()
        beat.cancel()
        writer.transport.abort()
        return ticks

    assert _run_with_deadline(scenario()) > 5


def test_write_completes_when_port_has_room(unread_port):
    async def scenario():
        _, writer = await open_mcu_serial(unread_port)
        async with asyncio.timeout(0.2):
            writer.write(bytes(34))
            await writer.drain()
        size = writer.transport.get_write_buffer_size()
        writer.transport.abort()
        return size

    assert _run_with_deadline(scenario()) == 0
