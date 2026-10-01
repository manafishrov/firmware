"""Source age uses the ROV monotonic clock; wall-clock changes do not alter it."""

import asyncio

import pytest

from manafish_sdk import Script
from rov_firmware.custom_actions.runtime import CustomActionRuntime


def test_stale_timeout_is_opt_in_and_rejects_invalid_limits():
    script = Script("sensor")
    assert script.reading("manual", bool).definition.stale_after_ms is None
    assert (
        script.reading("continuous", float, stale_after=2).definition.stale_after_ms
        == 2000
    )
    for index, invalid in enumerate((0, -1, float("nan"), float("inf"))):
        with pytest.raises(ValueError):
            script.reading(f"invalid_{index}", float, stale_after=invalid)


def test_snapshot_reports_elapsed_age_and_repeat_publication_resets_it(
    rov_state, tmp_path, monkeypatch
):
    clock = [10.0]
    monkeypatch.setattr(
        "rov_firmware.custom_actions.runtime.time.monotonic", lambda: clock[0]
    )
    runtime = CustomActionRuntime(rov_state, tmp_path)
    script = Script("sensor")
    script.reading("wet", bool)
    runtime._register(script._seal())
    runtime.publish("sensor.wet", False)
    runtime.samples["sensor.wet"]._recorded_at = clock[0]
    clock[0] += 5
    first = next(s for s in runtime.catalog()["samples"] if s["id"] == "sensor.wet")
    assert first["ageMs"] == 5000
    assert runtime.events[-1].model_dump(by_alias=True)["ageMs"] == 5000
    assert first["value"] is False
    runtime.publish("sensor.wet", False)
    runtime.samples["sensor.wet"]._recorded_at = clock[0]
    second = next(s for s in runtime.catalog()["samples"] if s["id"] == "sensor.wet")
    assert second["ageMs"] == 0
    assert second["sequence"] > first["sequence"]


def test_first_enable_does_not_claim_a_reading_has_arrived(rov_state, tmp_path):
    runtime = CustomActionRuntime(rov_state, tmp_path)

    async def scenario():
        await runtime.install(
            'from manafish_sdk import Script\nscript = Script("sensor")\nwet = script.reading("wet", bool)'
        )
        await runtime.enable("sensor", True)
        assert "sensor.wet" not in runtime.samples
        runtime.publish("sensor.wet", False)
        await runtime.enable("sensor", False)
        assert runtime.samples["sensor.wet"].value is None
        await runtime.shutdown()

    asyncio.run(scenario())
