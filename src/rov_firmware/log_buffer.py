"""Nonblocking, bounded local journal output for the control event loop."""

import logging
import queue
import threading


class BoundedJournalHandler(logging.Handler):
    """Drop oldest records under backpressure rather than block motor control."""

    def __init__(self, sink: logging.Handler, capacity: int = 256) -> None:
        """Start one daemon writer; no file or stream writes occur in emit()."""
        super().__init__()
        self._sink = sink
        self._records: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=capacity)
        self._drop_lock = threading.Lock()
        self._dropped = 0
        self.dropped_total = 0
        threading.Thread(target=self._drain, name="journal-writer", daemon=True).start()

    def emit(self, record: logging.LogRecord) -> None:
        """Enqueue without waiting for journal IO."""
        try:
            self._records.put_nowait(record)
        except queue.Full:
            try:
                self._records.get_nowait()
            except queue.Empty:
                pass
            else:
                with self._drop_lock:
                    self._dropped += 1
                    self.dropped_total += 1
            try:
                self._records.put_nowait(record)
            except queue.Full:
                # Handler.handle serializes producers; this also tolerates direct emit.
                with self._drop_lock:
                    self._dropped += 1
                    self.dropped_total += 1

    def _drain(self) -> None:
        while True:
            record = self._records.get()
            with self._drop_lock:
                dropped = self._dropped
                self._dropped = 0
            try:
                if dropped:
                    self._sink.handle(
                        logging.LogRecord(
                            "journal-buffer",
                            logging.WARNING,
                            "",
                            0,
                            "Local journal queue discarded %s older records under backpressure",
                            (dropped,),
                            None,
                        )
                    )
                self._sink.handle(record)
            except Exception:
                # A failed journal sink must never terminate the control service.
                with self._drop_lock:
                    self._dropped += 1
                    self.dropped_total += 1
