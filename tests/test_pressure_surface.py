from typing import cast

import pytest

from rov_firmware.constants import (
    GRAVITY,
    PASCAL_PER_KILOPASCAL,
    SURFACE_PRESSURE_CAPTURE_SAMPLES,
    SURFACE_PRESSURE_MAX_ABOVE_PA,
    SURFACE_PRESSURE_MAX_BELOW_PA,
    SURFACE_PRESSURE_PA,
)
from rov_firmware.sensors.pressure import PressureSensor
from rov_firmware.sensors.smp2000 import Smp2000, Smp2000Measurement


class FakeSensor:
    def __init__(self, pressure_kpa, temperature_c=20.0):
        self.pressure_kpa = pressure_kpa
        self.temperature_c = temperature_c
        self.samples_requested = None

    def measure(self):
        return Smp2000Measurement(self.pressure_kpa, self.temperature_c)

    def measure_average(self, samples):
        self.samples_requested = samples
        if isinstance(self.pressure_kpa, Exception):
            raise self.pressure_kpa
        return self.pressure_kpa


def _capture(rov_state, pressure_kpa):
    fake = FakeSensor(pressure_kpa)
    captured = PressureSensor(rov_state)._capture_surface_pressure(cast(Smp2000, fake))
    return captured, fake


def test_surface_pressure_is_captured_from_an_averaged_reading(rov_state):
    captured, fake = _capture(rov_state, 99.8)

    assert captured == pytest.approx(99_800.0)
    assert fake.samples_requested == SURFACE_PRESSURE_CAPTURE_SAMPLES


def test_surface_capture_rejects_a_reading_taken_underwater(rov_state):
    # Just past the upper bound: roughly what booting half a metre down reads.
    underwater_pa = SURFACE_PRESSURE_PA + SURFACE_PRESSURE_MAX_ABOVE_PA + 1.0

    captured, _ = _capture(rov_state, underwater_pa / PASCAL_PER_KILOPASCAL)

    assert captured == SURFACE_PRESSURE_PA


def test_surface_capture_accepts_the_edges_of_the_plausible_band(rov_state):
    highest_pa = SURFACE_PRESSURE_PA + SURFACE_PRESSURE_MAX_ABOVE_PA
    lowest_pa = SURFACE_PRESSURE_PA - SURFACE_PRESSURE_MAX_BELOW_PA

    high, _ = _capture(rov_state, highest_pa / PASCAL_PER_KILOPASCAL)
    low, _ = _capture(rov_state, lowest_pa / PASCAL_PER_KILOPASCAL)

    assert high == pytest.approx(highest_pa)
    assert low == pytest.approx(lowest_pa)


def test_surface_capture_rejects_an_implausibly_low_reading(rov_state):
    too_low_pa = SURFACE_PRESSURE_PA - SURFACE_PRESSURE_MAX_BELOW_PA - 1.0

    captured, _ = _capture(rov_state, too_low_pa / PASCAL_PER_KILOPASCAL)

    assert captured == SURFACE_PRESSURE_PA


def test_surface_capture_falls_back_when_no_reading_succeeds(rov_state):
    captured, _ = _capture(rov_state, None)

    assert captured == SURFACE_PRESSURE_PA


def test_surface_capture_falls_back_when_the_sensor_errors(rov_state):
    captured, _ = _capture(rov_state, OSError("i2c bus error"))

    assert captured == SURFACE_PRESSURE_PA


def test_depth_is_measured_against_the_captured_surface_pressure(rov_state):
    pressure_sensor = PressureSensor(rov_state)
    pressure_sensor.surface_pressure_pa = 99_000.0
    pressure_sensor.fluid_density = 1000.0
    # Exactly one metre of water above the captured surface pressure.
    one_metre_down_kpa = (99_000.0 + 1000.0 * GRAVITY) / PASCAL_PER_KILOPASCAL
    pressure_sensor.sensor = cast(Smp2000, FakeSensor(one_metre_down_kpa))

    data = pressure_sensor.read_data()

    assert data is not None
    assert data.depth == pytest.approx(1.0)


def test_depth_reads_zero_at_the_captured_surface_pressure(rov_state):
    pressure_sensor = PressureSensor(rov_state)
    pressure_sensor.surface_pressure_pa = 98_250.0
    pressure_sensor.sensor = cast(Smp2000, FakeSensor(98.25))

    data = pressure_sensor.read_data()

    assert data is not None
    assert data.depth == pytest.approx(0.0)


def test_read_data_reports_the_sensor_temperature(rov_state):
    pressure_sensor = PressureSensor(rov_state)
    pressure_sensor.sensor = cast(Smp2000, FakeSensor(101.325, temperature_c=12.5))

    data = pressure_sensor.read_data()

    assert data is not None
    assert data.temperature == pytest.approx(12.5)
