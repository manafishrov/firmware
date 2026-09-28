import asyncio
import base64
import json
import os
from pathlib import Path
import py_compile
import sys
import threading
import time
from unittest.mock import AsyncMock

import numpy as np
import pytest

from manafish_sdk import RovState
from rov_firmware.extensions.api import dispatch
from rov_firmware.extensions.csv_store import CsvStore
from rov_firmware.extensions.runtime import ExtensionRuntime
from rov_firmware.extensions.validation import validate_source
from rov_firmware.extensions.values import normalize_value
from rov_firmware.rov_state import RovState as FirmwareRovState


EXAMPLES = Path(__file__).parent / "fixtures" / "extensions"


def source(name):
    return (EXAMPLES / f"{name}.py").read_text()


async def wait_until(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
def runtime(rov_state, tmp_path):
    return ExtensionRuntime(rov_state, tmp_path / "extensions")


@pytest.mark.parametrize(
    "name",
    [
        "water_sensor",
        "dispenser",
        "depth_logger",
    ],
)
def test_script_declarations_load(name):
    manifest = validate_source(source(name))
    assert manifest.sdk_version == 1


def test_validation_imports_declarations_without_invoking_actions(tmp_path):
    marker = tmp_path / "executed"
    code = source("dispenser").replace(
        "    state.calls +=",
        f'    __import__("pathlib").Path({str(marker)!r}).touch()\n    state.calls +=',
    )
    assert validate_source(code).id == "dispenser"
    assert not marker.exists()
    with pytest.raises(ValueError, match="exactly one Script"):
        validate_source("MANIFEST = {}")
    with pytest.raises(RuntimeError, match="bad import"):
        validate_source('raise RuntimeError("bad import")\n' + code)


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (True, "number"),
        (1, "boolean"),
        (float("nan"), "number"),
        ([1, float("inf")], "numberArray"),
        ([[1]], "numberArray"),
        ("1", "number"),
    ],
)
def test_wrong_values_rejected(value, kind):
    with pytest.raises(ValueError):
        normalize_value(value, kind)


def test_numpy_normalizes():
    assert normalize_value(np.array([1.5, 2]), "numberArray") == [1.5, 2]
    assert normalize_value(np.float64(1.5), "number") == 1.5


def test_catalog_initial_snapshot_and_repeated_events(runtime):
    runtime._register(validate_source(source("dispenser")))
    runtime.publish("dispenser.count", 2)
    first = runtime.samples["dispenser.count"]
    runtime.publish("dispenser.count", 2)
    second = runtime.samples["dispenser.count"]
    assert second.sequence > first.sequence
    catalog = runtime.catalog()
    assert any(item["id"] == "rov.depth" for item in catalog["readings"])
    assert any(item["id"] == "dispenser.count" for item in catalog["readings"])
    assert any(
        item["id"] == "dispenser.dispense.running" for item in catalog["readings"]
    )
    assert catalog["samples"]


def test_install_preserves_source_and_invalid_update_keeps_previous(runtime):
    async def scenario():
        original = source("dispenser").replace("\n", "\r\n")
        info = await runtime.install(original)
        assert info["enabled"] is False
        assert await dispatch(runtime, "extension.source", {"id": "dispenser"}) == {
            "source": original
        }
        with pytest.raises(SyntaxError):
            await runtime.install("this is not python!")
        assert (runtime.directory / "dispenser.py").read_bytes() == original.encode()
        assert not runtime.runners
        await runtime.shutdown()

    asyncio.run(scenario())


def test_real_extension_state_and_single_invocation(runtime):
    async def scenario():
        await runtime.install(source("dispenser"))
        with pytest.raises(ValueError, match="Enable"):
            await runtime.invoke("dispenser.dispense")
        info = await runtime.enable("dispenser", True)
        assert info["status"] == "running", info
        try:
            for count in (1, 2):
                await runtime.invoke("dispenser.dispense")
                await wait_until(
                    lambda count=count: (
                        runtime.samples.get("dispenser.count") is not None
                        and runtime.samples["dispenser.count"].value == count
                        and not runtime.running
                    )
                )
            assert runtime.samples["dispenser.dispense.running"].value is False
        finally:
            await runtime.shutdown()
        assert not runtime.runners

    asyncio.run(scenario())


def test_real_logger_toggle_hold_stop_and_download(runtime):
    async def scenario():
        await runtime.install(source("depth_logger"))
        await runtime.enable("depth_logger", True)
        try:
            await runtime.configure("depth_logger.record", "toggle", 50)
            await runtime.invoke("depth_logger.record")
            await wait_until(
                lambda: (
                    len(runtime.csv.list()) > 0 and runtime.csv.list()[0]["rows"] >= 2
                )
            )
            await runtime.invoke("depth_logger.record")
            before = runtime.csv.list()[0]["rows"]
            await asyncio.sleep(0.12)
            assert runtime.csv.list()[0]["rows"] == before
            await runtime.configure("depth_logger.record", "hold", 50)
            await runtime.invoke("depth_logger.record")
            await wait_until(lambda: runtime.csv.list()[0]["rows"] > before)
            await runtime.invoke("depth_logger.record", "release")
            assert not runtime.running
            snapshot = runtime.csv.open("depth.csv")
            chunk = runtime.csv.read(snapshot["token"], 0)
            assert chunk["eof"]
            assert len(base64.b64decode(chunk["data"])) == snapshot["size"]
            runtime.csv.close(snapshot["token"])
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_disconnect_stops_operator_tasks_but_restarts_opted_in_sensor(runtime):
    async def scenario():
        await runtime.install(source("water_sensor"))
        await runtime.install(source("depth_logger"))
        await runtime.enable("water_sensor", True)
        await runtime.enable("depth_logger", True)
        try:
            await runtime.invoke("depth_logger.record")
            await wait_until(lambda: len(runtime.csv.list()) > 0)
            old_sensor = runtime.runners["water_sensor"]
            await runtime.disconnected()
            assert not runtime.running
            assert "depth_logger" not in runtime.runners
            assert runtime.runners["water_sensor"] != old_sensor
            await runtime.connected()
            assert "depth_logger" in runtime.runners
            assert not runtime.running
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_cooperative_action_cleans_up_on_disconnect(runtime):
    async def scenario():
        blocking = source("dispenser").replace(
            "    state.calls",
            "    try:\n        await __import__('asyncio').sleep(30)\n    finally:\n        ctx.rov.pressure.depth = 7.0\n    state.calls",
        )
        await runtime.install(blocking)
        await runtime.enable("dispenser", True)
        try:
            await runtime.invoke("dispenser.dispense")
            await asyncio.sleep(0.05)
            started = time.monotonic()
            runtime.refresh_builtins()
            await runtime.disconnected()
            assert time.monotonic() - started < 2
            assert not runtime.running
            assert not runtime.runners
            assert runtime.state.pressure.depth == 7.0
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_extension_error_reported_without_crashing_host(runtime, monkeypatch):
    warnings = []
    monkeypatch.setattr("rov_firmware.extensions.runtime.log_error", warnings.append)

    async def scenario():
        invalid = source("dispenser").replace(
            "await count.publish(state.calls)",
            'await count.publish("wrong type")',
        )
        await runtime.install(invalid)
        await runtime.enable("dispenser", True)
        try:
            await runtime.invoke("dispenser.dispense")
            await wait_until(lambda: runtime.extensions["dispenser"].status == "error")
            assert "valid number" in runtime.extensions["dispenser"].error
            assert any("valid number" in warning for warning in warnings)
            runtime.refresh_builtins()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_csv_snapshot_and_quoted_rows(tmp_path):
    store = CsvStore(tmp_path)
    store.append(["a,b", "line\nbreak"], "sensor.csv")
    assert store.list() == [
        {
            "name": "sensor.csv",
            "rows": 1,
            "columns": 2,
            "size": (tmp_path / "sensor.csv").stat().st_size,
        }
    ]
    snapshot = store.open("sensor.csv")
    store.append([1, 2], "sensor.csv")
    store.delete("sensor.csv")
    assert isinstance(snapshot["token"], str)
    read = store.read(snapshot["token"], 0)
    assert read["eof"] and read["nextOffset"] == snapshot["size"]
    assert isinstance(read["data"], str)
    assert base64.b64decode(read["data"]) == b'"a,b","line\nbreak"\r\n'
    store.close_all()
    assert not list(store.snapshots.iterdir())


@pytest.mark.parametrize(
    "name", ["../file.csv", "/absolute/file.csv", "bad.txt", "a/b.csv"]
)
def test_csv_rejects_paths(tmp_path, name):
    with pytest.raises(ValueError):
        CsvStore(tmp_path).append([1], name)


def test_csv_rejects_inconsistent_width_and_quota(tmp_path, monkeypatch):
    store = CsvStore(tmp_path)
    store.append([1, 2], "file.csv")
    with pytest.raises(ValueError, match="columns"):
        store.append([3], "file.csv")
    monkeypatch.setattr("rov_firmware.extensions.csv_store.MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="quota"):
        store.append([3, 4], "file.csv")


def test_uncancelled_task_prevents_replacement_and_keeps_ownership(
    runtime, monkeypatch
):
    monkeypatch.setattr("rov_firmware.extensions.runner.CANCELLATION_TIMEOUT", 0.02)

    async def scenario():
        uncooperative = source("dispenser").replace(
            "    state.calls",
            "    import asyncio\n"
            "    while not ctx.rov.system_status.depth_hold:\n"
            "        try:\n"
            "            await asyncio.sleep(0.01)\n"
            "        except asyncio.CancelledError:\n"
            "            pass\n"
            "    state.calls",
        )
        await runtime.install(uncooperative)
        await runtime.enable("dispenser", True)
        try:
            await runtime.invoke("dispenser.dispense")
            await asyncio.sleep(0.02)
            runner = runtime.runners["dispenser"]
            with pytest.raises(TimeoutError, match="ignored cancellation"):
                await runtime.invoke("dispenser.dispense", "stop")
            assert runtime.extensions["dispenser"].status == "error"
            with pytest.raises(TimeoutError):
                await runtime.install(source("dispenser"))
            assert runtime.runners["dispenser"] is runner
            assert (runtime.directory / "dispenser.py").read_text() == uncooperative
        finally:
            runtime.state.system_status.depth_hold = True
            await asyncio.sleep(0.05)
            await runtime.shutdown()

    asyncio.run(scenario())


def test_configuration_survives_restart_without_replaying_actions(runtime, rov_state):
    async def scenario():
        await runtime.install(source("depth_logger"))
        await runtime.enable("depth_logger", True)
        await runtime.configure("depth_logger.record", "hold", 500)
        await runtime.shutdown()
        replacement = ExtensionRuntime(rov_state, runtime.directory)
        try:
            await replacement.initialize()
            assert replacement.extensions["depth_logger"].enabled
            assert replacement.actions["depth_logger.record"].mode == "hold"
            assert replacement.actions["depth_logger.record"].interval_ms == 500
            assert not replacement.running
            assert replacement.csv.list() == []
        finally:
            await replacement.shutdown()

    asyncio.run(scenario())


def test_script_removal_cleans_catalog_samples_and_pending_events(runtime):
    async def scenario():
        await runtime.install(source("dispenser"))
        await runtime.enable("dispenser", True)
        try:
            await runtime.invoke("dispenser.dispense")
            await wait_until(
                lambda: (
                    "dispenser.count" in runtime.samples
                    and runtime.samples["dispenser.count"].value == 1
                )
            )
            await runtime.remove("dispenser")
            catalog = runtime.catalog()
            for collection in ("readings", "actions", "samples"):
                assert not any(
                    item["id"].startswith("dispenser.") for item in catalog[collection]
                )
            assert not any(item.id.startswith("dispenser.") for item in runtime.events)
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_csv_multiple_chunks_exact_reassembly_and_invalid_offsets(tmp_path):
    store = CsvStore(tmp_path)
    for index in range(2000):
        store.append([index, "sample" * 10], "long.csv")
    expected = (tmp_path / "long.csv").read_bytes()
    assert len(expected) > 65536
    snapshot = store.open("long.csv")
    token = snapshot["token"]
    assert isinstance(token, str)
    with pytest.raises(ValueError, match="offset"):
        store.read(token, -1)
    with pytest.raises(ValueError, match="offset"):
        store.read(token, len(expected) + 1)
    with pytest.raises(KeyError):
        store.read("unknown", 0)
    combined = bytearray()
    offset = 0
    while True:
        chunk = store.read(token, offset)
        assert isinstance(chunk["data"], str)
        data = base64.b64decode(chunk["data"])
        assert len(data) <= 65536
        combined.extend(data)
        offset = chunk["nextOffset"]
        assert isinstance(offset, int)
        if chunk["eof"]:
            break
    assert combined == expected
    assert store.read(token, len(expected))["data"] == ""
    store.close(token)
    with pytest.raises(KeyError):
        store.read(token, 0)


def test_failed_atomic_install_retains_old_source_and_registry(runtime, monkeypatch):
    async def scenario():
        original = source("dispenser")
        await runtime.install(original)
        manifest = runtime.manifests["dispenser"]

        def fail_replace(_source, _target):
            msg = "disk failure"
            raise OSError(msg)

        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(OSError, match="disk failure"):
            await runtime.install(
                original.replace("Dispenser (simulated)", "Replacement")
            )
        assert runtime.manifests["dispenser"] is manifest
        assert (runtime.directory / "dispenser.py").read_bytes() == original.encode()
        await runtime.shutdown()

    asyncio.run(scenario())


def test_capability_contract_fixture_matches_live_definitions(runtime):

    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "capability-catalog.json").read_text()
    )
    for name in ["water_sensor", "dispenser", "depth_logger"]:
        runtime._register(validate_source(source(name)))
    actual = runtime.catalog()
    for sample in actual["samples"]:
        sample["timestamp"] = 0
        sample["ageMs"] = 0
    assert actual == expected


def test_corrupt_settings_does_not_crash_or_enable_code(rov_state, tmp_path):
    directory = tmp_path / "extensions"
    directory.mkdir()
    (directory / "settings.json").write_text(
        '{"dispenser": {"enabled": "yes", "actions": 9}}'
    )
    (directory / "dispenser.py").write_text(source("dispenser"))
    runtime = ExtensionRuntime(rov_state, directory)
    asyncio.run(runtime.initialize())
    assert not runtime.extensions["dispenser"].enabled
    assert not runtime.runners
    asyncio.run(runtime.shutdown())


def test_sdk_cannot_override_managed_action_running_reading(runtime):
    runtime._register(validate_source(source("dispenser")))
    with pytest.raises(ValueError, match="declared"):
        asyncio.run(
            runtime._context("dispenser")._publish_reading("dispense.running", True)
        )
    assert runtime.samples["dispenser.dispense.running"].value is False


def test_unattended_startup_requires_background_opt_in(runtime, rov_state):
    async def scenario():
        await runtime.install(source("water_sensor"))
        await runtime.install(source("dispenser"))
        local_sensor = (
            source("water_sensor")
            .replace("_ctx: Context", "ctx: Context")
            .replace('"water_sensor"', '"connected_sensor"')
            .replace("continue_on_disconnect=True", "continue_on_disconnect=False")
        )
        await runtime.install(local_sensor)
        for identifier in list(runtime.extensions):
            await runtime.enable(identifier, True)
        await runtime.shutdown()
        replacement = ExtensionRuntime(rov_state, runtime.directory)
        try:
            await replacement.initialize()
            assert set(replacement.runners) == {"water_sensor"}
            await replacement.connected()
            assert set(replacement.runners) == {
                "water_sensor",
                "connected_sensor",
                "dispenser",
            }
            assert not replacement.running
        finally:
            await replacement.shutdown()

    asyncio.run(scenario())


def test_same_size_update_ignores_old_timestamp_bytecode(runtime, monkeypatch):
    async def scenario():
        original = source("dispenser")
        await runtime.install(original)
        path = runtime.directory / "dispenser.py"
        timestamp = path.stat().st_mtime
        py_compile.compile(str(path), doraise=True)
        original_replace = Path.replace

        def replace_and_preserve_timestamp(temporary, destination):
            result = original_replace(temporary, destination)
            if Path(destination).suffix == ".py":
                os.utime(destination, (timestamp, timestamp))
            return result

        monkeypatch.setattr(Path, "replace", replace_and_preserve_timestamp)
        await runtime.enable("dispenser", True)
        try:
            changed = original.replace("+= 1", "+= 2")
            assert len(changed) == len(original) and changed != original
            await runtime.install(changed)
            await runtime.invoke("dispenser.dispense")
            await wait_until(
                lambda: (
                    runtime.samples.get("dispenser.count") is not None
                    and runtime.samples["dispenser.count"].value == 2
                )
            )
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_context_exposes_original_typed_objects_and_live_updates(runtime):

    context = runtime._context("example")
    assert RovState is FirmwareRovState
    assert context.rov is runtime.state
    assert context.rov.pressure is runtime.state.pressure
    assert context.rov.imu.acceleration is runtime.state.imu.acceleration
    runtime.state.pressure.depth = 23.5
    assert context.rov.pressure.depth == 23.5
    runtime.state.imu.acceleration[0] = 4
    assert context.rov.imu.acceleration[0] == 4
    assert not hasattr(context, "read")
    assert not hasattr(context, "invoke")


def test_extension_uses_live_state_and_real_typed_methods(runtime):

    async def scenario():
        runtime.state.pico = AsyncMock()
        runtime.state.pressure.depth = 3.5
        script = source("dispenser").replace(
            "await count.publish(state.calls)",
            "await ctx.rov.set_desired_depth(ctx.rov.pressure.depth)\n"
            "    await count.publish(ctx.rov.pressure.depth)",
        )
        await runtime.install(script)
        await runtime.enable("dispenser", True)
        try:
            await runtime.invoke("dispenser.dispense")
            await wait_until(lambda: not runtime.running)
            runtime.state.pico.set_desired_depth.assert_awaited_once_with(3.5)
            assert runtime.samples["dispenser.count"].value == 3.5
            runtime.state.pressure.depth = 8.5
            await runtime.invoke("dispenser.dispense")
            await wait_until(lambda: not runtime.running)
            runtime.state.pico.set_desired_depth.assert_awaited_with(8.5)
            assert runtime.samples["dispenser.count"].value == 8.5
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_background_reads_fresh_state_without_websocket_or_sampling(runtime):
    async def scenario():
        script = (
            source("water_sensor")
            .replace("_ctx: Context", "ctx: Context")
            .replace('script.reading("wet", bool', 'script.reading("wet", float')
            .replace(
                "await wet.publish(False)",
                "await wet.publish(ctx.rov.pressure.depth)\n"
                '        await ctx.log_csv([ctx.rov.pressure.depth], "offline.csv")',
            )
            .replace("asyncio.sleep(1)", "asyncio.sleep(0.01)")
        )
        await runtime.install(script)
        await runtime.enable("water_sensor", True)
        try:
            await runtime.disconnected()
            runtime.state.pressure.depth = 17.25
            await wait_until(
                lambda: (
                    runtime.csv.list()
                    and "17.25" in (runtime.csv.directory / "offline.csv").read_text()
                )
            )
            assert runtime.samples["water_sensor.wet"].value == 17.25
            assert runtime.samples["rov.depth"].value != 17.25
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_import_failure_releases_module_and_preserves_installed_source(runtime):
    async def scenario():
        original = source("dispenser")
        await runtime.install(original)
        modules = set(sys.modules)
        with pytest.raises(ValueError, match="bad driver"):
            await runtime.install(original + '\nraise ValueError("bad driver")\n')
        assert (runtime.directory / "dispenser.py").read_text() == original
        assert not any(
            name.startswith("manafish_script_") for name in set(sys.modules) - modules
        )
        assert not runtime.runners
        await runtime.shutdown()

    asyncio.run(scenario())


def test_csv_write_finishes_before_repeated_cancellation_returns(runtime, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original = runtime.csv.append

    def slow_append(values, filename):
        started.set()
        assert release.wait(timeout=3)
        original(values, filename)

    monkeypatch.setattr(runtime.csv, "append", slow_append)

    async def scenario():
        context = runtime._context("example")
        write = asyncio.create_task(context.log_csv([1], "cleanup.csv"))
        try:
            await wait_until(started.is_set)
            write.cancel()
            await asyncio.sleep(0)
            write.cancel()
            await asyncio.sleep(0)
            assert not write.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await write
            assert runtime.csv.list()[0]["rows"] == 1
        finally:
            release.set()
            await asyncio.gather(write, return_exceptions=True)
            await runtime.shutdown()

    asyncio.run(scenario())
