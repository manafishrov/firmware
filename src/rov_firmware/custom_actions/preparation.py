"""Bounded off-loop imports with exact-source reuse until a runner takes ownership."""

import asyncio
from collections import OrderedDict
from contextlib import suppress
import threading

from .loading import LoadedScript, load_script


IMPORT_TIMEOUT = 10.0
MAX_PREPARED_SCRIPTS = 8


class ScriptPreparation:
    """Own prepared modules and at most one import that has not yet returned."""

    def __init__(self) -> None:
        """Keep imports separate from the event loop and active script instances."""
        self._cache: OrderedDict[str, LoadedScript] = OrderedDict()
        self._lock = asyncio.Lock()
        self._pending: asyncio.Task[LoadedScript] | None = None
        self._abandoned = threading.Event()
        self._closed = False

    async def prepare(self, source: str) -> LoadedScript:
        """Reuse exact bytes, importing once for validation, save, and first enable."""
        async with self._lock:
            if self._closed:
                msg = "Custom action loader has stopped"
                raise RuntimeError(msg)
            cached = self._cache.get(source)
            if cached is not None:
                self._cache.move_to_end(source)
                return cached
            if self._pending is not None and not self._pending.done():
                msg = "A previous custom action import is still running; wait for it to finish"
                raise RuntimeError(msg)
            loaded = await self._import(source)
            if self._closed:
                loaded.close()
                msg = "Custom action loader has stopped"
                raise RuntimeError(msg)
            self._cache[source] = loaded
            while len(self._cache) > MAX_PREPARED_SCRIPTS:
                _, discarded = self._cache.popitem(last=False)
                discarded.close()
            return loaded

    async def take(self, source: str) -> LoadedScript:
        """Transfer a fresh module to one runner; live module state is never reused."""
        loaded = await self.prepare(source)
        # No await between retrieving and transferring ownership.
        return self._cache.pop(source, loaded)

    async def _import(self, source: str) -> LoadedScript:
        abandoned = threading.Event()
        self._abandoned = abandoned

        def load() -> LoadedScript:
            loaded = load_script(source)
            if abandoned.is_set():
                loaded.close()
            return loaded

        task = asyncio.create_task(asyncio.to_thread(load))
        self._pending = task
        try:
            loaded = await asyncio.wait_for(asyncio.shield(task), IMPORT_TIMEOUT)
            self._pending = None
            return loaded
        except BaseException as error:
            abandoned.set()
            task.add_done_callback(_discard)
            if isinstance(error, TimeoutError):
                msg = f"Custom action import exceeded {IMPORT_TIMEOUT:g} seconds"
                raise TimeoutError(msg) from error
            raise

    def close(self) -> None:
        """Release cached modules and discard any late result after shutdown."""
        self._closed = True
        self._abandoned.set()
        for loaded in self._cache.values():
            loaded.close()
        self._cache.clear()
        if self._pending is not None:
            self._pending.add_done_callback(_discard)


def _discard(task: asyncio.Task[LoadedScript]) -> None:
    with suppress(BaseException):
        task.result().close()
