from rov_firmware.sensors.pi_power import is_pi_undervoltage_detected


def _create_hwmon_sensor(root, index: int, name: str, alarm: str) -> None:
    sensor = root / f"hwmon{index}"
    sensor.mkdir()
    (sensor / "name").write_text(name, encoding="ascii")
    (sensor / "in0_lcrit_alarm").write_text(alarm, encoding="ascii")


def test_reads_raspberry_pi_undervoltage_alarm(tmp_path):
    _create_hwmon_sensor(tmp_path, 0, "other_sensor\n", "1\n")
    _create_hwmon_sensor(tmp_path, 3, "rpi_volt\n", "1\n")

    assert is_pi_undervoltage_detected(tmp_path)


def test_reports_normal_voltage_when_alarm_is_clear(tmp_path):
    _create_hwmon_sensor(tmp_path, 1, "rpi_volt\n", "0\n")

    assert not is_pi_undervoltage_detected(tmp_path)


def test_reports_unavailable_sensor_as_normal(tmp_path):
    assert not is_pi_undervoltage_detected(tmp_path)


def test_skips_unreadable_or_incomplete_hwmon_devices(tmp_path):
    incomplete = tmp_path / "hwmon0"
    incomplete.mkdir()
    (incomplete / "name").write_text("rpi_volt\n", encoding="ascii")
    _create_hwmon_sensor(tmp_path, 1, "rpi_volt\n", "1\n")

    assert is_pi_undervoltage_detected(tmp_path)
