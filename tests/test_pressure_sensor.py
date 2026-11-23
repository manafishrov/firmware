from types import SimpleNamespace
from typing import Any, cast

import pytest

from rov_firmware.constants import (
    DENSITY_SALTWATER,
    GRAVITY,
    PRESSURE_SENSOR_RECONNECT_INTERVAL_S,
)
from rov_firmware.sensors import pressure as pressure_module
from rov_firmware.sensors.pressure import PressureSensor
from rov_firmware.sensors.smp2000 import Smp2000Measurement


class StopLoopError(Exception):
    pass


class FakeSmp2000:
    def __init__(self):
        self.connected = True
        self.open_calls = 0

    def open(self):
        self.open_calls += 1
        if not self.connected:
            raise OSError(121, "Remote I/O error")

    def measure(self):
        if not self.connected:
            raise OSError(5, "Input/output error")
        return Smp2000Measurement(pressure_kpa=106.325, temperature_c=18.0)


def run_read_loop(sensor, rov_state, monkeypatch, script, stop_at):
    clock = [0.0]
    health = []

    def sleep(seconds):
        clock[0] += max(seconds, 0.001)
        script(clock[0])
        health.append((clock[0], rov_state.system_health.pressure_sensor_healthy))
        if clock[0] >= stop_at:
            raise StopLoopError

    monkeypatch.setattr(
        pressure_module,
        "time",
        SimpleNamespace(
            sleep=sleep, monotonic=lambda: clock[0], perf_counter=lambda: clock[0]
        ),
    )
    with pytest.raises(StopLoopError):
        sensor._blocking_read_loop()
    return health


def test_pressure_sensor_reconnects_after_being_unplugged(rov_state, monkeypatch):
    smp2000 = FakeSmp2000()
    sensor = PressureSensor(rov_state)
    sensor.sensor = cast(Any, smp2000)
    # The fake reads 5 kPa above this reference, so depth should stay put while
    # the sensor drops out and comes back. The loop picks the density itself
    # from the config, so derive the expected depth the same way.
    sensor.surface_pressure_pa = 101_325.0
    expected_depth = 5_000.0 / (DENSITY_SALTWATER * GRAVITY)
    rov_state.system_health.pressure_sensor_healthy = True

    def script(now):
        smp2000.connected = not 1.0 <= now < 25.0

    health = run_read_loop(sensor, rov_state, monkeypatch, script, stop_at=40.0)

    lost = next(now for now, healthy in health if not healthy)
    restored = next(now for now, healthy in health if now > lost and healthy)
    assert lost < 2.0
    assert 25.0 <= restored <= 25.0 + PRESSURE_SENSOR_RECONNECT_INTERVAL_S + 1.5
    # One failed attempt per interval while unplugged, then the successful one.
    assert smp2000.open_calls == 3
    assert rov_state.pressure.depth == pytest.approx(expected_depth)


def test_pressure_sensor_missing_at_boot_is_retried(rov_state, monkeypatch):
    smp2000 = FakeSmp2000()
    sensor = PressureSensor(rov_state)
    monkeypatch.setattr(pressure_module, "Smp2000", lambda _calibration: smp2000)
    rov_state.system_health.pressure_sensor_healthy = False

    run_read_loop(sensor, rov_state, monkeypatch, lambda _now: None, stop_at=12.0)

    assert sensor.sensor is smp2000
    assert rov_state.system_health.pressure_sensor_healthy


def test_reconnect_does_not_rezero_the_surface_reference(rov_state, monkeypatch):
    # An outage that ends underwater must not re-zero depth at that depth.
    smp2000 = FakeSmp2000()
    sensor = PressureSensor(rov_state)
    sensor.sensor = cast(Any, smp2000)
    sensor.surface_pressure_pa = 99_000.0
    rov_state.system_health.pressure_sensor_healthy = True

    def script(now):
        smp2000.connected = not 1.0 <= now < 15.0

    run_read_loop(sensor, rov_state, monkeypatch, script, stop_at=30.0)

    assert sensor.surface_pressure_pa == pytest.approx(99_000.0)
