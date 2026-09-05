import asyncio
from collections import deque
import logging
import queue
import threading
from unittest.mock import AsyncMock, Mock

import pytest

from rov_firmware import log
from rov_firmware.constants import CRASH_LOG_SEND_TIMEOUT_S
from rov_firmware.log_buffer import BoundedJournalHandler
from rov_firmware.models.log import LogLevel
from rov_firmware.websocket import server


class ExitRaceLock:
    """Insert a real producer after the empty decision, before the flag reset."""

    def __init__(self):
        self.lock = threading.Lock()
        self.exits = 0

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, *_args):
        self.exits += 1
        trigger = self.exits == 2
        self.lock.release()
        if trigger:
            producer = threading.Thread(
                target=lambda: log.log_info("arrived during flusher exit"), daemon=True
            )
            producer.start()
            producer.join(timeout=2)
            assert not producer.is_alive()


@pytest.fixture
def isolated_stream(monkeypatch):
    stream = asyncio.Queue()
    monkeypatch.setattr(log, "_pending_logs", deque(maxlen=log._MAX_PENDING_LOGS))
    monkeypatch.setattr(log, "_pending_lock", threading.Lock())
    monkeypatch.setattr(log, "_dropped_logs", 0)
    monkeypatch.setattr(log, "_flush_scheduled", False)
    monkeypatch.setattr(log, "get_message_queue", lambda: stream)
    monkeypatch.setattr(log.websocket_state, "is_client_connected", True)
    monkeypatch.setattr(log.websocket_state, "main_event_loop", None)
    monkeypatch.setattr(log._logger, "handlers", [logging.NullHandler()])
    monkeypatch.setattr(log._logger, "propagate", False)
    return stream


def test_threaded_arrival_during_flusher_exit_is_delivered_without_another_log(
    isolated_stream, monkeypatch
):
    monkeypatch.setattr(log, "_pending_lock", ExitRaceLock())
    monkeypatch.setattr(log, "_flush_scheduled", True)

    async def run():
        monkeypatch.setattr(
            log.websocket_state, "main_event_loop", asyncio.get_running_loop()
        )
        await log._flush_when_connected()
        message = await asyncio.wait_for(isolated_stream.get(), timeout=1)
        assert message.payload.message.endswith("arrived during flusher exit")
        assert isolated_stream.empty()
        assert not log._pending_logs
        assert not log._flush_scheduled

    asyncio.run(run())


def test_cancelled_flusher_preserves_pending_logs_without_rescheduling(
    isolated_stream, monkeypatch
):
    entered = asyncio.Event()
    schedule = Mock()
    monkeypatch.setattr(log, "_schedule_flush", schedule)
    monkeypatch.setattr(log, "_flush_scheduled", True)
    log.log_info("pending at cancellation")
    schedule.reset_mock()

    async def blocked_flush():
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(log, "flush_pending_logs", blocked_flush)

    async def run():
        task = asyncio.create_task(log._flush_when_connected())
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        schedule.assert_not_called()
        assert not log._flush_scheduled
        assert len(log._pending_logs) == 1
        assert isolated_stream.empty()

    asyncio.run(run())


class ConsumerRaceQueue(queue.Queue):
    """Allow a consumer to drain after Full, before the producer handles it."""

    def __init__(self):
        super().__init__(maxsize=1)
        self.full_observed = threading.Event()
        self.consumed = threading.Event()

    def put_nowait(self, item):
        try:
            super().put_nowait(item)
        except queue.Full:
            self.full_observed.set()
            assert self.consumed.wait(timeout=2)
            raise


def test_consumer_winning_eviction_race_does_not_increment_drop_counts(monkeypatch):
    # Use a controlled consumer instead of the handler's autonomous drain loop.
    monkeypatch.setattr(BoundedJournalHandler, "_drain", lambda _self: None)
    handler = BoundedJournalHandler(logging.NullHandler(), capacity=1)
    records = ConsumerRaceQueue()
    handler._records = records
    old = logging.LogRecord("test", logging.INFO, "", 0, "old", (), None)
    new = logging.LogRecord("test", logging.INFO, "", 0, "new", (), None)
    records.put_nowait(old)
    consumed = []

    def consume():
        if records.full_observed.wait(timeout=2):
            consumed.append(records.get_nowait())
            records.consumed.set()

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        handler.handle(new)
    finally:
        consumer.join(timeout=3)
        handler.close()
    assert not consumer.is_alive()
    assert consumed == [old]
    assert records.get_nowait() is new
    assert records.empty()
    assert handler._dropped == 0
    assert handler.dropped_total == 0


class BlockedSink(logging.Handler):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.unblock = threading.Event()
        self.timed_out = threading.Event()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())
        self.entered.set()
        if not self.unblock.wait(timeout=5):
            self.timed_out.set()


@pytest.mark.parametrize("send_fails", [False, True])
def test_crash_and_internal_error_logging_use_bounded_nonblocking_journal(
    monkeypatch, send_fails
):
    # Assert the production routing, not a replacement logger injected into server.
    assert server._logger is log.get_local_logger()
    assert not server._logger.propagate
    assert any(
        isinstance(handler, BoundedJournalHandler)
        for handler in server._logger.handlers
    )
    sink = BlockedSink()
    handler = BoundedJournalHandler(sink, capacity=4)
    monkeypatch.setattr(log.get_local_logger(), "handlers", [handler])
    monkeypatch.setattr(log.get_local_logger(), "propagate", False)
    instance = object.__new__(server.WebsocketServer)
    send_frame = AsyncMock(
        side_effect=OSError("synthetic socket failure") if send_fails else None
    )
    monkeypatch.setattr(instance, "send_frame", send_frame)

    async def run():
        for _ in range(12):
            await instance.send_log_now(LogLevel.ERROR, "synthetic crash")

    try:
        log.get_local_logger().error("occupy journal worker")
        assert sink.entered.wait(timeout=1)
        asyncio.run(run())
        # Every socket attempt finished while the journal worker remained blocked.
        assert not sink.unblock.is_set()
        assert not sink.timed_out.is_set()
        assert send_frame.await_count == 12
        assert handler._records.qsize() == 4
        assert handler.dropped_total == 12 * (2 if send_fails else 1) - 4
        frame = send_frame.await_args_list[0].args[0]
        assert "session=" in frame.payload.message
        assert frame.payload.message.endswith("synthetic crash")
        assert send_frame.await_args_list[0].kwargs == {
            "timeout": CRASH_LOG_SEND_TIMEOUT_S
        }
    finally:
        sink.unblock.set()
        handler.close()
