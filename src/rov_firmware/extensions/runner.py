"""Supervised async extension tasks with direct access to live firmware objects."""

import asyncio
from collections.abc import Callable

from pydantic import JsonValue

from .declarations import ActionFunction, BackgroundFunction
from .loading import LoadedScript
from .sdk import Context


CANCELLATION_TIMEOUT = 1.0


class ExtensionRunner:
    """Keep task ownership and cancellation explicit for trusted cooperative code."""

    def __init__(
        self,
        loaded: LoadedScript,
        context: Context,
        on_running: Callable[[str, bool], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Prepare a runner without importing the extension."""
        self.context = context
        self.on_running = on_running
        self.on_error = on_error
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.loaded = loaded
        self.closing = False

    async def start(self) -> None:
        """Load the exact installed source and schedule its optional background."""
        try:
            self.loaded.script._bind(self.context)
            function = self.loaded.script._background
            if function is not None:
                self.tasks["background"] = asyncio.create_task(
                    self._background(function)
                )
        except BaseException:
            await self.stop()
            raise

    async def _background(self, function: BackgroundFunction) -> None:
        try:
            await function(self.context)
        except Exception as error:
            self.on_error(f"background: {error}")

    def invoke(
        self, identifier: str, value: JsonValue, mode: str, interval_ms: int
    ) -> None:
        """Schedule one action, repeating only after the prior call completes."""
        if self.closing:
            msg = "Extension is not running"
            raise RuntimeError(msg)
        previous = self.tasks.get(identifier)
        if previous is not None and not previous.done():
            return
        function = self.loaded.script._actions[identifier]
        self.tasks[identifier] = asyncio.create_task(
            self._execute(identifier, function, value, mode, interval_ms)
        )

    async def _execute(
        self,
        identifier: str,
        function: ActionFunction,
        value: JsonValue,
        mode: str,
        interval_ms: int,
    ) -> None:
        self.on_running(identifier, True)
        try:
            while True:
                await function(self.context, value)
                if mode == "once":
                    break
                await asyncio.sleep(interval_ms / 1000)
        except Exception as error:
            self.on_error(f"{identifier}: {error}")
        finally:
            self.on_running(identifier, False)

    @staticmethod
    async def _cancel(tasks: list[asyncio.Task[None]]) -> None:
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=CANCELLATION_TIMEOUT)
            if pending:
                msg = (
                    "Extension ignored cancellation; it must finish before replacement"
                )
                raise TimeoutError(msg)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel(self, identifier: str) -> None:
        """Wait for action cleanup; never start a replacement over live work."""
        task = self.tasks.get(identifier)
        if task is not None:
            await self._cancel([task])

    async def stop(self) -> None:
        """Cancel all owned tasks; Python code must cooperate with cancellation."""
        self.closing = True
        self.context.close()
        await self._cancel(list(self.tasks.values()))
        self.loaded.close()
