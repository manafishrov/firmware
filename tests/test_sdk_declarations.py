"""Typed SDK discovery, publication ownership and action signature regressions."""

import asyncio
from pathlib import Path
import sys
from typing import assert_type, cast

from gpiozero import Device
from gpiozero.pins.mock import MockFactory
import numpy as np
from numpy.typing import NDArray
import pytest

from manafish_sdk import Context, Reading, Script, Trigger
from rov_firmware.extensions.csv_store import CsvStore
from rov_firmware.extensions.loading import load_script
from rov_firmware.extensions.runtime import ExtensionRuntime
from rov_firmware.extensions.validation import validate_source


HEADER = 'from manafish_sdk import Context, Script\nscript = Script("test")\n'


def test_declarations_derive_types_and_keep_the_original_function():
    script = Script("test")
    wet = script.reading("wet", bool)
    assert isinstance(wet, Reading)
    assert_type(wet, Reading[bool])
    assert_type(script.reading("depth", float), Reading[float])
    assert_type(
        script.reading("acceleration", NDArray[np.float64]),
        Reading[NDArray[np.float64]],
    )

    async def set_depth(ctx: Context, value: float) -> None:
        ctx.rov.pressure.depth = value

    registered = script.action(modes=(Trigger.ONCE, Trigger.HOLD))(set_depth)
    assert registered is set_depth
    definition = script._seal()
    assert definition.readings[0].value_type == "boolean"
    assert definition.actions[0].id == "set_depth"
    assert definition.actions[0].input_type == "number"
    assert definition.actions[0].modes == ["once", "hold"]
    with pytest.raises(RuntimeError, match="module level"):
        script.reading("late", bool)


@pytest.mark.parametrize(
    "body, message",
    [
        ('script.reading("wet", bool)\nscript.reading("wet", bool)', "Duplicate"),
        ('script.reading("for", bool)', "identifier"),
        ('script.reading("wet", dict)', "Use bool"),
        ("@script.action()\ndef sample(ctx): pass", "async def"),
        ("@script.action()\nasync def sample(ctx, value): pass", "Use bool"),
        ("@script.action()\nasync def sample(ctx, *, value: float): pass", "async def"),
        ("@script.action()\nasync def background(ctx): pass", "reserved"),
        (
            "@script.background()\nasync def monitor(ctx): pass\n@script.background()\nasync def other(ctx): pass",
            "exactly one background",
        ),
        ('other = Script("other")', "exactly one Script"),
    ],
)
def test_invalid_declarations_fail_during_discovery(body, message):
    before = set(sys.modules)
    with pytest.raises((ValueError, TypeError), match=message):
        validate_source(HEADER + body)
    assert not {
        name
        for name in set(sys.modules) - before
        if name.startswith("manafish_script_")
    }


def test_failed_import_does_not_stop_other_scripts_at_startup(rov_state, tmp_path):
    (tmp_path / "broken.py").write_text('raise RuntimeError("bad dependency")')
    (tmp_path / "test.py").write_text(HEADER)
    runtime = ExtensionRuntime(rov_state, tmp_path)
    asyncio.run(runtime.initialize())
    assert set(runtime.extensions) == {"test", "broken"}
    assert runtime.extensions["broken"].status == "error"
    assert runtime.extensions["broken"].error is not None
    assert "bad dependency" in runtime.extensions["broken"].error
    asyncio.run(runtime.shutdown())


def test_duplicate_namespace_revisions_have_independent_readings(rov_state, tmp_path):
    source = HEADER + 'wet = script.reading("wet", bool)\n'
    first, second = load_script(source), load_script(source)
    calls = []
    context = Context(
        rov_state, lambda *args: calls.append(args), CsvStore(tmp_path), "test"
    )
    first.script._bind(context)
    try:
        assert first.module is not second.module
        asyncio.run(first.module.wet.publish(True))
        assert calls == [("wet", True)]
        with pytest.raises(RuntimeError, match="enabled"):
            asyncio.run(second.module.wet.publish(False))
        context.close()
        with pytest.raises(RuntimeError, match="stopped"):
            asyncio.run(first.module.wet.publish(False))
        assert calls == [("wet", True)]
    finally:
        first.close()
        second.close()


def test_publication_retains_boolean_type_and_rejects_coercion(rov_state, tmp_path):
    script = Script("test")
    wet = script.reading("wet", bool)
    callback = []
    script._bind(
        Context(
            rov_state, lambda *args: callback.append(args), CsvStore(tmp_path), "test"
        )
    )
    asyncio.run(wet.publish(True))
    asyncio.run(wet.publish(None))
    for wrong in (1, "true", 0.0):
        with pytest.raises(ValueError):
            asyncio.run(wet.publish(cast(bool, wrong)))
    assert callback == [("wet", True), ("wet", None)]


def test_typed_action_input_and_explicit_stable_id(rov_state, tmp_path):
    runtime = ExtensionRuntime(rov_state, tmp_path)
    source = (
        HEADER
        + """
@script.action(identifier="old_name")
async def renamed(ctx: Context, value: float) -> None:
    ctx.rov.pressure.depth = value
"""
    )

    async def scenario():
        await runtime.install(source)
        await runtime.enable("test", True)
        try:
            await runtime.invoke("test.old_name", value=12.5)
            await asyncio.gather(*runtime.runners["test"].tasks.values())
            assert runtime.state.pressure.depth == 12.5
            with pytest.raises(ValueError):
                await runtime.invoke("test.old_name", value="not a number")
            assert runtime.state.pressure.depth == 12.5
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_validation_keeps_active_module_and_never_invokes_hardware(rov_state, tmp_path):
    runtime = ExtensionRuntime(rov_state, tmp_path)
    source = (
        HEADER
        + """
@script.action()
async def sample(ctx: Context) -> None:
    raise RuntimeError("hardware should not be accessed during discovery")
"""
    )

    async def scenario():
        await runtime.install(source)
        await runtime.enable("test", True)
        loaded = runtime.runners["test"].loaded
        try:
            assert loaded is not None
            for _ in range(3):
                await runtime.validate(source)
                assert sys.modules[loaded.module.__name__] is loaded.module
            assert runtime.extensions["test"].status == "running"
            assert not runtime.runners["test"].tasks
        finally:
            await runtime.shutdown()
        assert loaded.module.__name__ not in sys.modules

    asyncio.run(scenario())


def test_water_sensor_example_uses_gpio_and_shared_readings(
    rov_state, tmp_path, monkeypatch
):
    source = (
        Path(__file__).parents[1] / "examples/extensions/water_sensor.py"
    ).read_text()
    factory = MockFactory()
    monkeypatch.setattr(Device, "pin_factory", factory)
    runtime = ExtensionRuntime(rov_state, tmp_path)
    notifications = []
    monkeypatch.setattr(
        "rov_firmware.extensions.sdk.toast_content",
        lambda **kw: notifications.append(kw),
    )

    async def wait_sample(previous_sequence=0):
        async with asyncio.timeout(2):
            while True:
                reading = runtime.samples.get("water_sensor.wet")
                if reading is not None and reading.sequence > previous_sequence:
                    return reading
                await asyncio.sleep(0.001)

    async def scenario():
        await runtime.install(source)
        await runtime.enable("water_sensor", True)
        loaded = runtime.runners["water_sensor"].loaded
        assert loaded is not None
        assert set(loaded.script._actions) == {"toggle_monitoring"}
        real_device = loaded.module.DigitalInputDevice
        monkeypatch.setattr(loaded.module, "SAMPLE_INTERVAL_SECONDS", 0.005)
        expected_wet = True

        def device(pin):
            result = real_device(pin)
            if expected_wet:
                factory.pin(pin).drive_high()
            return result

        monkeypatch.setattr(loaded.module, "DigitalInputDevice", device)
        try:
            sequence = 0
            for wet in (True, True, False, False):
                expected_wet = wet
                reading = await wait_sample(sequence)
                sequence = reading.sequence
                assert reading.value is wet
                assert not any(factory._reservations.values())
            assert len(notifications) == 2
            assert notifications[0]["content"].message == "Water detected"
            assert notifications[1]["content"].message == "Water sensor dry"

        finally:
            await runtime.shutdown()
        assert not any(factory._reservations.values())

    asyncio.run(scenario())


def test_water_sensor_background_lifecycle(rov_state, tmp_path, monkeypatch):
    source = (
        Path(__file__).parents[1] / "examples/extensions/water_sensor.py"
    ).read_text()
    factory = MockFactory()
    monkeypatch.setattr(Device, "pin_factory", factory)
    runtime = ExtensionRuntime(rov_state, tmp_path)

    async def wait_sample(instance, previous_sequence=0):
        async with asyncio.timeout(2):
            while True:
                reading = instance.samples.get("water_sensor.wet")
                if (
                    reading is not None
                    and reading.sequence > previous_sequence
                    and reading.value is not None
                ):
                    return reading
                await asyncio.sleep(0.001)

    async def scenario():
        await runtime.install(source)
        await runtime.enable("water_sensor", True)
        try:
            reading = await wait_sample(runtime)
            await runtime.invoke("water_sensor.toggle_monitoring")
            await runtime.runners["water_sensor"].tasks["toggle_monitoring"]
            assert runtime.samples["water_sensor.wet"].value is None
            await runtime.disconnected()
            assert "water_sensor" in runtime.runners
            await wait_sample(runtime, reading.sequence)
            await runtime.enable("water_sensor", False)
            assert "water_sensor" not in runtime.runners
            sequence = runtime.samples["water_sensor.wet"].sequence
            await asyncio.sleep(0.02)
            assert runtime.samples["water_sensor.wet"].sequence == sequence
            assert not any(factory._reservations.values())
            await runtime.enable("water_sensor", True)
            await wait_sample(runtime, sequence)
            await runtime.invoke("water_sensor.toggle_monitoring")
            await runtime.runners["water_sensor"].tasks["toggle_monitoring"]
        finally:
            await runtime.shutdown()
        assert not any(factory._reservations.values())

        # Persisted enablement starts monitoring before an app connects.
        replacement = ExtensionRuntime(rov_state, tmp_path)
        try:
            await replacement.initialize()
            reading = await wait_sample(replacement)
            assert reading.value is False
        finally:
            await replacement.shutdown()
        assert not any(factory._reservations.values())

    asyncio.run(scenario())


def test_invalid_installed_script_remains_editable_and_removable(rov_state, tmp_path):
    from_source = 'MANIFEST = {"sdkVersion": 1, "id": "test", "name": "Test"}\n'
    (tmp_path / "test.py").write_text(from_source)
    runtime = ExtensionRuntime(rov_state, tmp_path)

    async def scenario():
        await runtime.initialize()
        await runtime.connected()
        assert runtime.extensions["test"].status == "error"
        assert not runtime.runners
        with pytest.raises(ValueError, match="Edit and save"):
            await runtime.enable("test", True)
        await runtime.install(HEADER)
        await runtime.enable("test", True)
        assert runtime.extensions["test"].status == "running"
        await runtime.remove("test")
        assert not (tmp_path / "test.py").exists()
        await runtime.shutdown()

    asyncio.run(scenario())


def test_numpy_reading_preserves_typed_array_until_publication(rov_state, tmp_path):
    code = (
        HEADER
        + """
import numpy as np
from numpy.typing import NDArray
acceleration = script.reading("acceleration", NDArray[np.float64])

@script.action()
async def sample(ctx: Context) -> None:
    await acceleration.publish(ctx.rov.imu.acceleration)
"""
    )
    runtime = ExtensionRuntime(rov_state, tmp_path)

    async def scenario():
        await runtime.install(code)
        await runtime.enable("test", True)
        try:
            runtime.state.imu.acceleration[:] = [1, 2, 3]
            await runtime.invoke("test.sample")
            await asyncio.gather(*runtime.runners["test"].tasks.values())
            assert runtime.samples["test.acceleration"].value == [1, 2, 3]
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
