import asyncio
from collections import deque
import logging
import threading
import time

import pytest

from rov_firmware import log
from rov_firmware.log_buffer import BoundedJournalHandler
from rov_firmware.websocket.state import websocket_state


@pytest.fixture
def isolated_logs(monkeypatch):
    queue = asyncio.Queue()
    monkeypatch.setattr(log, "_pending_logs", deque(maxlen=log._MAX_PENDING_LOGS))
    monkeypatch.setattr(log, "_dropped_logs", 0)
    monkeypatch.setattr(log, "_flush_scheduled", False)
    monkeypatch.setattr(log, "get_message_queue", lambda: queue)
    monkeypatch.setattr(websocket_state, "is_client_connected", False)
    monkeypatch.setattr(websocket_state, "main_event_loop", None)
    return queue


def test_early_logs_replay_with_generation_timestamp(isolated_logs, monkeypatch):
    monkeypatch.setattr(log.time, "monotonic", lambda: 12.345)
    log.log_error("early failure")
    monkeypatch.setattr(log.time, "monotonic", lambda: 50.0)
    asyncio.run(log.flush_pending_logs())
    message = isolated_logs.get_nowait().payload.message
    assert "mono_s=12.345" in message
    assert "session=" in message and "boot=" in message and "utc=" in message
    assert message.endswith("early failure")


def test_offline_buffer_keeps_latest_logs_and_reports_loss(isolated_logs):
    for index in range(log._MAX_PENDING_LOGS + 4):
        log.log_info(f"entry-{index}")
    asyncio.run(log.flush_pending_logs())
    warning = isolated_logs.get_nowait().payload.message
    assert "discarded 4 older records" in warning
    assert isolated_logs.get_nowait().payload.message.endswith("entry-4")
    remaining = []
    while not isolated_logs.empty():
        remaining.append(isolated_logs.get_nowait())
    assert remaining[-1].payload.message.endswith("entry-103")
    assert not log._pending_logs
    assert log._dropped_logs == 0


def test_connected_logs_are_in_both_journal_and_stream(
    isolated_logs, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(log._logger, "propagate", True)

    async def run():
        monkeypatch.setattr(
            websocket_state, "main_event_loop", asyncio.get_running_loop()
        )
        monkeypatch.setattr(websocket_state, "is_client_connected", True)
        log.log_warn("connected failure")
        message = await asyncio.wait_for(isolated_logs.get(), 1)
        assert message.payload.message.endswith("connected failure")
        assert not log._pending_logs

    asyncio.run(run())
    assert sum("connected failure" in record.message for record in caplog.records) == 1


def test_slow_client_backlog_is_bounded_without_dropping_control(isolated_logs):
    control = object()
    for _ in range(log._MAX_LOG_QUEUE_DEPTH):
        isolated_logs.put_nowait(control)
    for index in range(1500):
        log.log_info(f"slow-client-{index}")
    asyncio.run(log.flush_pending_logs())
    assert isolated_logs.qsize() == log._MAX_LOG_QUEUE_DEPTH
    assert len(log._pending_logs) == log._MAX_PENDING_LOGS
    assert log._dropped_logs == 1400
    while not isolated_logs.empty():
        assert isolated_logs.get_nowait() is control
    asyncio.run(log.flush_pending_logs())
    assert "discarded 1400" in isolated_logs.get_nowait().payload.message
    replay = []
    while not isolated_logs.empty():
        replay.append(isolated_logs.get_nowait())
    assert replay[-1].payload.message.endswith("slow-client-1499")


def test_blocked_journal_sink_cannot_block_producers():
    entered = threading.Event()
    release = threading.Event()
    received = []

    class SlowSink(logging.Handler):
        def emit(self, record):
            entered.set()
            release.wait(2)
            received.append(record.getMessage())

    handler = BoundedJournalHandler(SlowSink(), capacity=4)
    record = logging.LogRecord("test", logging.INFO, "", 0, "first", (), None)
    handler.handle(record)
    assert entered.wait(1)
    try:
        started = time.perf_counter()
        for index in range(100):
            handler.handle(
                logging.LogRecord(
                    "test", logging.INFO, "", 0, f"record-{index}", (), None
                )
            )
        assert time.perf_counter() - started < 0.1
        assert handler._records.qsize() == 4
        assert handler.dropped_total == 96
    finally:
        release.set()
