from types import SimpleNamespace
from typing import Any, cast

import pytest

from rov_firmware.constants import PRESSURE_SENSOR_RECONNECT_INTERVAL_S
from rov_firmware.sensors import pressure as pressure_module
from rov_firmware.sensors.pressure import PressureSensor


class StopLoopError(Exception):
    pass


class FakeMs5837:
    def __init__(self):
        self.connected = True
        self.init_calls = 0

    def init(self):
        self.init_calls += 1
        if not self.connected:
            raise OSError(121, "Remote I/O error")
        return True

    def read(self):
        if not self.connected:
            raise OSError(5, "Input/output error")
        return True

    def pressure(self):
        return 1063.0

    def temperature(self):
        return 18.0

    def depth(self):
        return 0.5

    def setFluidDensity(self, _density):  # noqa: N802 - ms5837 API name
        pass


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
    ms5837 = FakeMs5837()
    sensor = PressureSensor(rov_state)
    sensor.sensor = cast(Any, ms5837)
    rov_state.system_health.pressure_sensor_healthy = True

    def script(now):
        ms5837.connected = not 1.0 <= now < 25.0

    health = run_read_loop(sensor, rov_state, monkeypatch, script, stop_at=40.0)

    lost = next(now for now, healthy in health if not healthy)
    restored = next(now for now, healthy in health if now > lost and healthy)
    assert lost < 2.0
    assert 25.0 <= restored <= 25.0 + PRESSURE_SENSOR_RECONNECT_INTERVAL_S + 1.5
    # One failed attempt per interval while unplugged, then the successful one.
    assert ms5837.init_calls == 3
    assert rov_state.pressure.depth == pytest.approx(0.5)


def test_pressure_sensor_missing_at_boot_is_retried(rov_state, monkeypatch):
    ms5837 = FakeMs5837()
    sensor = PressureSensor(rov_state)
    monkeypatch.setattr(pressure_module, "MS5837_30BA", lambda: ms5837)
    rov_state.system_health.pressure_sensor_healthy = False

    run_read_loop(sensor, rov_state, monkeypatch, lambda _now: None, stop_at=12.0)

    assert sensor.sensor is ms5837
    assert rov_state.system_health.pressure_sensor_healthy
