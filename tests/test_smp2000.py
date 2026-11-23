import pytest

from rov_firmware.sensors.smp2000 import Smp2000, Smp2000Calibration, to_celsius


# The vendor communication instruction's worked example: a 20-120 kPa part
# returning the frame 04 9B B0 C5 56 AA.
EXAMPLE_BRIDGE_COUNTS = 0x9BB0C5
EXAMPLE_TEMPERATURE_COUNTS = 0x56AA
FULL_SCALE = 16777216


def test_pressure_conversion_matches_the_vendor_worked_example():
    sensor = Smp2000(
        Smp2000Calibration(
            pressure_min_kpa=20.0,
            pressure_max_kpa=120.0,
            span_min_counts=int(0.15 * FULL_SCALE),
            span_max_counts=int(0.85 * FULL_SCALE),
        )
    )

    assert sensor.to_kilopascal(EXAMPLE_BRIDGE_COUNTS) == pytest.approx(
        85.45229, abs=1e-3
    )


def test_temperature_conversion_matches_the_vendor_worked_example():
    assert to_celsius(EXAMPLE_TEMPERATURE_COUNTS) == pytest.approx(24.32, abs=0.01)
