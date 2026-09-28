"""Import ownership, reuse and control-loop responsiveness regressions."""

import asyncio
import sys
import threading
from unittest.mock import AsyncMock

import pytest

from rov_firmware.custom_actions import preparation
from rov_firmware.custom_actions.preparation import ScriptPreparation
from rov_firmware.custom_actions.runtime import CustomActionRuntime


SOURCE = 'from manafish_sdk import Script\nscript = Script("test")\n'


def test_validation_install_enable_share_one_import_and_reload_resets_state(
    rov_state, tmp_path
):
    counter = tmp_path / "imports"
    source = f"""
from pathlib import Path
from manafish_sdk import Script
counter = Path({str(counter)!r})
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1")
script = Script("test")
"""
    runtime = CustomActionRuntime(rov_state, tmp_path / "custom_actions")

    async def scenario():
        try:
            await runtime.validate(source)
            await runtime.validate(source)
            await runtime.install(source)
            await runtime.enable("test", True)
            assert counter.read_text() == "1"
            await runtime.enable("test", False)
            await runtime.enable("test", True)
            assert counter.read_text() == "2"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_slow_import_does_not_block_loop_or_builtin_controls(
    rov_state, tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    original = preparation.load_script

    def slow_load(source):
        started.set()
        assert release.wait(2)
        return original(source)

    monkeypatch.setattr(preparation, "load_script", slow_load)
    invoke = AsyncMock()
    monkeypatch.setattr("rov_firmware.custom_actions.runtime.builtins.invoke", invoke)
    runtime = CustomActionRuntime(rov_state, tmp_path)

    async def scenario():
        loading = asyncio.create_task(runtime.validate(SOURCE))
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(0.001)
                for _ in range(10):
                    runtime.refresh_builtins()
                    await runtime.invoke("rov.depthHold.toggle")
                    await asyncio.sleep(0.001)
            assert not loading.done()
            assert invoke.await_count == 10
            release.set()
            await loading
        finally:
            release.set()
            await asyncio.gather(loading, return_exceptions=True)
            await runtime.shutdown()

    asyncio.run(scenario())


def test_timeout_keeps_single_import_owned_and_discards_late_result(monkeypatch):
    release = threading.Event()
    original = preparation.load_script
    imported = []

    def slow_load(source):
        assert release.wait(2)
        result = original(source)
        imported.append(result)
        return result

    monkeypatch.setattr(preparation, "load_script", slow_load)
    monkeypatch.setattr(preparation, "IMPORT_TIMEOUT", 0.02)
    loader = ScriptPreparation()

    async def scenario():
        try:
            with pytest.raises(TimeoutError, match="import exceeded"):
                await loader.prepare(SOURCE)
            with pytest.raises(RuntimeError, match="still running"):
                await loader.prepare(SOURCE)
            release.set()
            async with asyncio.timeout(1):
                while not imported:
                    await asyncio.sleep(0.001)
            assert imported[0].module.__name__ not in sys.modules
            ready = await loader.prepare(SOURCE)
            assert ready is not imported[0]
        finally:
            release.set()
            loader.close()

    asyncio.run(scenario())


def test_cache_eviction_never_closes_a_runner_owned_module(monkeypatch):
    monkeypatch.setattr(preparation, "MAX_PREPARED_SCRIPTS", 1)
    loader = ScriptPreparation()

    async def scenario():
        active = await loader.take(SOURCE)
        first = await loader.prepare(SOURCE + "# first")
        second = await loader.prepare(SOURCE + "# second")
        assert first.module.__name__ not in sys.modules
        assert sys.modules[active.module.__name__] is active.module
        loader.close()
        assert second.module.__name__ not in sys.modules
        assert sys.modules[active.module.__name__] is active.module
        active.close()

    asyncio.run(scenario())


def test_cancelled_request_releases_late_import(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = preparation.load_script
    imported = []

    def slow_load(source):
        started.set()
        assert release.wait(2)
        result = original(source)
        imported.append(result)
        return result

    monkeypatch.setattr(preparation, "load_script", slow_load)
    loader = ScriptPreparation()

    async def scenario():
        task = asyncio.create_task(loader.prepare(SOURCE))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            async with asyncio.timeout(1):
                while not imported:
                    await asyncio.sleep(0.001)
            assert imported[0].module.__name__ not in sys.modules
        finally:
            release.set()
            loader.close()

    asyncio.run(scenario())
