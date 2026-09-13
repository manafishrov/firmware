import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rov_firmware.websocket import server


PERIOD = 1 / 60


class FakeClock:
    def __init__(self, state, count, oversleep=0.0):
        self.now = 100.0
        self.state = state
        self.count = count
        self.oversleep = oversleep
        self.delays = []

    def monotonic(self):
        return self.now

    async def sleep(self, delay):
        assert delay > 0, "Every iteration must yield without catching up"
        self.delays.append(delay)
        self.now += delay + self.oversleep
        self.oversleep = 0.0
        # Multiple updates between frames: only the newest is sampled.
        self.state.regulator.pitch += 1
        self.state.regulator.pitch += 1
        if len(self.delays) == self.count:
            raise asyncio.CancelledError

    def install(self, monkeypatch):
        monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=self.monotonic))
        monkeypatch.setattr(
            server,
            "asyncio",
            SimpleNamespace(sleep=self.sleep, CancelledError=asyncio.CancelledError),
        )


def run_cadence(
    monkeypatch, state, costs, *, build_and_lock_costs=(0.0, 0.0), oversleep=0.0
):
    build_cost, lock_cost = build_and_lock_costs
    instance = server.WebsocketServer(state, Mock())
    clock = FakeClock(state, len(costs), oversleep)
    starts = []
    frames = []
    build = server.build_telemetry

    def timed_build(state):
        starts.append(clock.now)
        clock.now += build_cost
        return build(state)

    class TimedLock:
        async def __aenter__(self):
            clock.now += lock_cost

        async def __aexit__(self, *_args):
            pass

    async def send(frame):
        # Exercise the real send_frame serialization and lock path.
        index = len(frames)
        frames.append(json.loads(frame))
        clock.now += costs[index]

    monkeypatch.setattr(instance, "client", SimpleNamespace(send=send))
    monkeypatch.setattr(instance, "_send_lock", TimedLock())
    monkeypatch.setattr(server, "build_telemetry", timed_build)
    clock.install(monkeypatch)
    asyncio.run(instance._send_telemetry_periodically())
    return starts, frames, clock.delays


@pytest.mark.parametrize(
    ("send_cost", "build_cost", "lock_cost"),
    [(0.0, 0.0, 0.0), (0.005, 0.0, 0.0), (0.005, 0.002, 0.003)],
)
def test_telemetry_work_counts_toward_60hz_period(
    rov_state, monkeypatch, send_cost, build_cost, lock_cost
):
    starts, frames, delays = run_cadence(
        monkeypatch,
        rov_state,
        [send_cost] * 61,
        build_and_lock_costs=(build_cost, lock_cost),
    )

    assert starts == pytest.approx([100.0 + i * PERIOD for i in range(61)])
    assert delays == pytest.approx([PERIOD - send_cost - build_cost - lock_cost] * 61)
    assert [frame["payload"]["pitch"] for frame in frames] == list(range(0, 122, 2))


@pytest.mark.parametrize("overrun", [PERIOD, 0.020, 0.100])
def test_telemetry_overruns_rebase_and_sleep_without_catch_up(
    rov_state, monkeypatch, overrun
):
    starts, frames, delays = run_cadence(
        monkeypatch, rov_state, [overrun, overrun, 0.0, 0.0]
    )

    assert starts == pytest.approx(
        [
            100.0,
            100.0 + overrun + PERIOD,
            100.0 + 2 * (overrun + PERIOD),
            100.0 + 2 * overrun + 3 * PERIOD,
        ]
    )
    assert delays == pytest.approx([PERIOD] * 4)
    assert [frame["payload"]["pitch"] for frame in frames] == [0, 2, 4, 6]


def test_telemetry_late_wakeup_drops_missed_slots(rov_state, monkeypatch):
    starts, _, delays = run_cadence(monkeypatch, rov_state, [0.0] * 4, oversleep=0.100)

    assert starts == pytest.approx(
        [100.0, 100.1 + PERIOD, 100.1 + 2 * PERIOD, 100.1 + 3 * PERIOD]
    )
    assert delays == pytest.approx([PERIOD] * 4)


@pytest.mark.parametrize("blocked_at", ["sleep", "send", "lock"])
def test_telemetry_cancellation_exits_and_releases_send_lock(
    rov_state, monkeypatch, blocked_at
):
    instance = server.WebsocketServer(rov_state, Mock())
    entered = asyncio.Event()
    frames = []

    async def block():
        entered.set()
        await asyncio.Future()

    async def send(frame):
        frames.append(frame)
        if blocked_at == "send":
            await block()

    async def sleep(_delay):
        await block()

    monkeypatch.setattr(instance, "client", SimpleNamespace(send=send))
    monkeypatch.setattr(
        server,
        "asyncio",
        SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError),
    )

    async def run():
        if blocked_at == "lock":
            await instance._send_lock.acquire()
        task = asyncio.create_task(instance._send_telemetry_periodically())
        try:
            if blocked_at == "lock":
                # Let the producer reach the held lock without a wall-clock delay.
                await asyncio.sleep(0)
                assert not frames
                assert not task.done()
            else:
                await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            await asyncio.wait_for(task, timeout=1)
            assert task.done()
            assert not task.cancelled()  # Preserve the existing graceful exit.
        finally:
            if blocked_at == "lock":
                instance._send_lock.release()
            if not task.done():
                task.cancel()
                await task
        assert not instance._send_lock.locked()
        assert len(frames) == (0 if blocked_at == "lock" else 1)

    asyncio.run(run())
