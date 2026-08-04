"""Raspberry Pi input-power monitoring."""

from pathlib import Path


HWMON_ROOT = Path("/sys/class/hwmon")
RPI_VOLTAGE_SENSOR_NAME = "rpi_volt"


def is_pi_undervoltage_detected(hwmon_root: Path = HWMON_ROOT) -> bool:
    """Return whether the Raspberry Pi firmware detected input undervoltage.

    The ``raspberrypi-hwmon`` kernel driver polls the firmware throttling flags
    and exposes the undervoltage alarm through ``in0_lcrit_alarm``. The hwmon
    index is assigned dynamically, so identify the sensor by name instead of
    assuming a fixed ``hwmonN`` path.

    Args:
        hwmon_root: hwmon class directory, injectable for tests.

    Returns:
        True while the kernel's Raspberry Pi voltage alarm is asserted. Missing
        or unreadable hwmon data is treated as unavailable rather than as an
        undervoltage event.
    """
    try:
        for device in hwmon_root.glob("hwmon*"):
            try:
                sensor_name = (device / "name").read_text(encoding="ascii").strip()
                if sensor_name != RPI_VOLTAGE_SENSOR_NAME:
                    continue
                alarm = (device / "in0_lcrit_alarm").read_text(encoding="ascii")
                return alarm.strip() == "1"
            except OSError:
                continue
    except OSError:
        return False

    return False
