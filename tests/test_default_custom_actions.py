import asyncio
import csv
import json

import pytest

from rov_firmware.custom_actions.runtime import DEFAULTS_DIRECTORY, CustomActionRuntime


DEFAULT_IDS = {"blackbox", "extended_telemetry", "water_sensor"}


async def wait_until(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "rov_firmware.custom_actions.sdk.toast_content",
        lambda **kw: sent.append(kw["content"].message),
    )
    return sent


@pytest.fixture
def directory(tmp_path):
    return tmp_path / "custom_actions"


def test_defaults_install_once_disabled_and_stay_removed(rov_state, directory):
    async def scenario():
        runtime = CustomActionRuntime(rov_state, directory, DEFAULTS_DIRECTORY)
        try:
            await runtime.initialize()
            assert set(runtime.custom_actions) == DEFAULT_IDS
            for info in runtime.custom_actions.values():
                assert not info.enabled
                assert info.status == "stopped"
            assert not runtime.runners
            await runtime.remove("blackbox")
        finally:
            await runtime.shutdown()

        replacement = CustomActionRuntime(rov_state, directory, DEFAULTS_DIRECTORY)
        try:
            await replacement.initialize()
            assert set(replacement.custom_actions) == DEFAULT_IDS - {"blackbox"}
        finally:
            await replacement.shutdown()

    asyncio.run(scenario())
    assert set(json.loads((directory / "defaults.json").read_text())) == DEFAULT_IDS


def test_defaults_never_replace_an_installed_script(rov_state, directory):
    directory.mkdir()
    source = (DEFAULTS_DIRECTORY / "water_sensor.py").read_text()
    edited = source.replace("WATER_SENSOR_GPIO_PIN = 17", "WATER_SENSOR_GPIO_PIN = 27")
    (directory / "water_sensor.py").write_text(edited)

    async def scenario():
        runtime = CustomActionRuntime(rov_state, directory, DEFAULTS_DIRECTORY)
        try:
            await runtime.initialize()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
    assert (directory / "water_sensor.py").read_text() == edited


def test_runtime_without_defaults_installs_nothing(rov_state, directory):
    async def scenario():
        runtime = CustomActionRuntime(rov_state, directory)
        try:
            await runtime.initialize()
            assert not runtime.custom_actions
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
    assert not (directory / "defaults.json").exists()


def test_blackbox_records_rows_and_toggles(
    rov_state, directory, notifications, monkeypatch
):
    runtime = CustomActionRuntime(rov_state, directory)

    def rows():
        files = runtime.csv.list()
        return files[0]["rows"] if files else 0

    async def scenario():
        await runtime.install((DEFAULTS_DIRECTORY / "blackbox.py").read_text())
        await runtime.enable("blackbox", True)
        module = runtime.runners["blackbox"].loaded.module
        monkeypatch.setattr(module, "LOG_INTERVAL_SECONDS", 0.01)
        try:
            await wait_until(lambda: rows() >= 3)
            assert runtime.samples["blackbox.logging"].value is True
            assert str(runtime.samples["blackbox.file"].value).startswith("blackbox_")

            await runtime.invoke("blackbox.toggle_logging")
            await runtime.runners["blackbox"].tasks["toggle_logging"]
            assert runtime.samples["blackbox.logging"].value is False
            paused = rows()
            await asyncio.sleep(0.05)
            assert rows() == paused
            assert notifications[-1] == "Blackbox logging paused"

            await runtime.invoke("blackbox.toggle_logging")
            await runtime.runners["blackbox"].tasks["toggle_logging"]
            await wait_until(lambda: rows() > paused)

            # A blackbox must keep recording when the operator connection drops.
            await runtime.disconnected()
            assert "blackbox" in runtime.runners
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
    # The restart after a disconnect may begin a second file; each has one header.
    recordings = sorted(runtime.csv.directory.glob("blackbox_*.csv"))
    assert recordings
    for recording in recordings:
        with recording.open(newline="") as stream:
            header, *body = csv.reader(stream)
        assert header[:4] == [
            "time (UTC)",
            "elapsed (s)",
            "depth (m)",
            "desiredDepth (m)",
        ]
        assert "thrusterRpms 8 (rpm)" in header
        assert all(row[0] != "time (UTC)" and len(row) == len(header) for row in body)


def run_blackbox(runtime, monkeypatch, until, timeout=10):
    """Record until a condition holds or the script stops, returning file names."""
    seen = []

    def check():
        sample = runtime.samples.get("blackbox.file")
        if sample is not None and sample.value not in seen:
            seen.append(sample.value)
        return until(seen) or runtime.custom_actions["blackbox"].status == "error"

    async def scenario():
        await runtime.install((DEFAULTS_DIRECTORY / "blackbox.py").read_text())
        await runtime.enable("blackbox", True)
        module = runtime.runners["blackbox"].loaded.module
        monkeypatch.setattr(module, "LOG_INTERVAL_SECONDS", 0.001)
        try:
            await wait_until(check, timeout)
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
    return seen


@pytest.mark.parametrize(
    "limits",
    [
        # Files rotate at the per-file limit and the oldest ones are deleted.
        (4000, 10000),
        # Only the current file fits beside other CSV files, so it is replaced.
        (64 * 1024 * 1024, 4000),
    ],
)
def test_blackbox_keeps_recording_by_deleting_its_oldest_files(
    rov_state, directory, notifications, monkeypatch, limits
):
    file_limit, blackbox_room = limits
    runtime = CustomActionRuntime(rov_state, directory)
    for _ in range(100):
        runtime.csv.append(["keep", "me"], "other.csv")
    other = (runtime.csv.directory / "other.csv").read_bytes()
    total_limit = len(other) + blackbox_room
    store = "rov_firmware.custom_actions.csv_store"
    monkeypatch.setattr(f"{store}.MAX_FILE_BYTES", file_limit)
    monkeypatch.setattr(f"{store}.MAX_TOTAL_BYTES", total_limit)

    seen = run_blackbox(runtime, monkeypatch, lambda seen: len(seen) >= 6)

    assert runtime.custom_actions["blackbox"].status != "error"
    assert "Blackbox logging stopped" not in notifications
    assert len(seen) >= 6
    assert (runtime.csv.directory / "other.csv").read_bytes() == other
    remaining = sorted(runtime.csv.directory.glob("blackbox_*.csv"))
    assert remaining
    assert seen[0] not in {path.name for path in remaining}
    assert sum(p.stat().st_size for p in runtime.csv.directory.glob("*.csv")) <= (
        total_limit
    )
    for recording in remaining:
        assert recording.stat().st_size <= file_limit
        with recording.open(newline="") as stream:
            header, *body = csv.reader(stream)
        assert header[0] == "time (UTC)"
        assert all(row[0] != "time (UTC)" and len(row) == len(header) for row in body)


def test_blackbox_stops_visibly_when_other_files_fill_storage(
    rov_state, directory, notifications, monkeypatch
):
    runtime = CustomActionRuntime(rov_state, directory)
    runtime.csv.append(["keep", "me"], "other.csv")
    other = (runtime.csv.directory / "other.csv").read_bytes()
    monkeypatch.setattr(
        "rov_firmware.custom_actions.csv_store.MAX_TOTAL_BYTES", len(other) + 100
    )

    run_blackbox(runtime, monkeypatch, lambda _: False)

    assert runtime.custom_actions["blackbox"].status == "error"
    assert "quota" in str(runtime.custom_actions["blackbox"].error)
    assert notifications[-1] == "Blackbox logging stopped"
    assert (runtime.csv.directory / "other.csv").read_bytes() == other
    assert not list(runtime.csv.directory.glob("blackbox_*.csv"))


def test_blackbox_reports_errors_other_than_quota(
    rov_state, directory, notifications, monkeypatch
):
    runtime = CustomActionRuntime(rov_state, directory)
    rows = 0

    def changing_width(seen):
        nonlocal rows
        if seen and rows == 0:
            rows = 1
            module = runtime.runners["blackbox"].loaded.module
            snapshot = module._snapshot
            monkeypatch.setattr(
                module,
                "_snapshot",
                lambda ctx: tuple([*part, 0] for part in snapshot(ctx)),
            )
        return False

    run_blackbox(runtime, monkeypatch, changing_width)

    assert runtime.custom_actions["blackbox"].status == "error"
    assert "columns" in str(runtime.custom_actions["blackbox"].error)
    assert notifications[-1] == "Blackbox logging stopped"
    assert len(list(runtime.csv.directory.glob("blackbox_*.csv"))) == 1


def test_extended_telemetry_reports_system_and_only_healthy_sensors(
    rov_state, directory, monkeypatch
):
    runtime = CustomActionRuntime(rov_state, directory)

    def value(identifier):
        sample = runtime.samples.get(f"extended_telemetry.{identifier}")
        return None if sample is None else sample.value

    async def scenario():
        await runtime.install(
            (DEFAULTS_DIRECTORY / "extended_telemetry.py").read_text()
        )
        await runtime.enable("extended_telemetry", True)
        module = runtime.runners["extended_telemetry"].loaded.module
        monkeypatch.setattr(module, "SAMPLE_INTERVAL_SECONDS", 0.01)
        try:
            await wait_until(lambda: value("network_sent") is not None)
            assert 0 <= value("cpu_usage") <= 100
            assert value("cpu_core_usage")
            assert value("firmware_memory") > 0
            assert value("event_loop_lag") >= 0
            assert value("imu_acceleration") is None
            assert value("esc_voltages") is None

            rov_state.system_health.imu_healthy = True
            rov_state.system_health.mcu_healthy = True
            await wait_until(lambda: value("imu_acceleration") is not None)
            assert value("imu_acceleration") == [0.0, 0.0, 0.0]
            await wait_until(lambda: value("esc_voltages") is not None)
            assert len(value("esc_voltages")) == 8

            # Diagnostics are only for a connected operator.
            await runtime.disconnected()
            assert "extended_telemetry" not in runtime.runners
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
