"""Pressure sensor interface for the ROV firmware."""

import asyncio
import math
import time

from ..constants import (
    DENSITY_FRESHWATER,
    DENSITY_SALTWATER,
    DEPTH_DERIVATIVE_EMA_TAU,
    GRAVITY,
    MBAR_PER_KILOPASCAL,
    PASCAL_PER_KILOPASCAL,
    PRESSURE_SENSOR_READ_FREQUENCY,
    PRESSURE_SENSOR_RECONNECT_INTERVAL_S,
    SMP2000_PRESSURE_MAX_KPA,
    SMP2000_PRESSURE_MIN_KPA,
    SMP2000_SPAN_MAX_COUNTS,
    SMP2000_SPAN_MIN_COUNTS,
    SURFACE_PRESSURE_CAPTURE_SAMPLES,
    SURFACE_PRESSURE_MAX_ABOVE_PA,
    SURFACE_PRESSURE_MAX_BELOW_PA,
    SURFACE_PRESSURE_PA,
    SYSTEM_FAILURE_THRESHOLD,
)
from ..log import log_error, log_info, log_warn
from ..models.config import FluidType
from ..models.sensors import PressureData
from ..rov_state import RovState
from ..toast import ToastContent, toast_error
from .smp2000 import Smp2000, Smp2000Calibration


class PressureSensor:
    """Pressure sensor class."""

    def __init__(self, state: RovState):
        """Initialize the pressure sensor.

        Args:
            state: The ROV state.
        """
        self.state: RovState = state
        self.sensor: Smp2000 | None = None
        self.current_fluid_type: FluidType | None = None
        self.fluid_density: float = DENSITY_FRESHWATER
        self.surface_pressure_pa: float = SURFACE_PRESSURE_PA
        self._next_reconnect_time: float = 0.0
        self._reconnect_failure_logged: bool = False

    async def initialize(self) -> None:
        """Asynchronously initialize the pressure sensor."""
        try:
            log_info("Attempting to initialize SMP2000 pressure sensor...")
            await asyncio.to_thread(self._open_sensor)
            sensor = self.sensor
            if sensor is None:
                message = "SMP2000 pressure sensor was not opened"
                raise RuntimeError(message)
            self.surface_pressure_pa = await asyncio.to_thread(
                self._capture_surface_pressure, sensor
            )
            self.state.system_health.pressure_sensor_healthy = True
            log_info("SMP2000 pressure sensor initialized successfully.")
            await asyncio.to_thread(self._check_achievable_read_rate, sensor)
        except Exception as e:
            self.state.system_health.pressure_sensor_healthy = False
            log_error(
                f"Failed to initialize SMP2000 pressure sensor. Is it connected? Error: {e}"
            )
            toast_error(
                identifier=None,
                content=ToastContent(
                    message_key="toasts_pressure_sensor_init_failed",
                    description_key="toasts_pressure_sensor_init_failed_description",
                ),
                action=None,
            )

    def _open_sensor(self) -> None:
        """Open the sensor and confirm it completes a conversion.

        Reuses the existing driver instance when one exists, so reconnecting
        after the sensor was unplugged does not leak bus handles.
        """
        if self.sensor is None:
            self.sensor = Smp2000(
                Smp2000Calibration(
                    pressure_min_kpa=SMP2000_PRESSURE_MIN_KPA,
                    pressure_max_kpa=SMP2000_PRESSURE_MAX_KPA,
                    span_min_counts=SMP2000_SPAN_MIN_COUNTS,
                    span_max_counts=SMP2000_SPAN_MAX_COUNTS,
                )
            )
        self.sensor.open()
        self._update_fluid_density()

    def _capture_surface_pressure(self, sensor: Smp2000) -> float:
        """Measure the pressure to treat as zero depth.

        Runs once at startup, before the read loop, so depth is relative to the
        actual surface pressure at this place and time. A capture outside the
        plausible band around standard atmospheric pressure falls back to the
        standard value, which keeps a Pi that boots underwater from silently
        zeroing depth at the wrong level.

        Deliberately not repeated when the sensor reconnects: an outage that
        ends underwater would otherwise re-zero depth at that depth.

        Args:
            sensor: The opened sensor to read.

        Returns:
            The surface reference pressure in pascal.
        """
        standard_kpa = SURFACE_PRESSURE_PA / PASCAL_PER_KILOPASCAL
        try:
            pressure_kpa = sensor.measure_average(SURFACE_PRESSURE_CAPTURE_SAMPLES)
        except Exception as e:
            log_error(
                f"Could not capture surface pressure, using {standard_kpa:.3f} kPa: {e}"
            )
            return SURFACE_PRESSURE_PA
        if pressure_kpa is None:
            log_warn(
                f"No surface pressure reading, using {standard_kpa:.3f} kPa. "
                "Depth will drift with the weather until the next restart."
            )
            return SURFACE_PRESSURE_PA
        pressure_pa = pressure_kpa * PASCAL_PER_KILOPASCAL
        lowest = SURFACE_PRESSURE_PA - SURFACE_PRESSURE_MAX_BELOW_PA
        highest = SURFACE_PRESSURE_PA + SURFACE_PRESSURE_MAX_ABOVE_PA
        if not lowest <= pressure_pa <= highest:
            log_warn(
                f"Captured surface pressure {pressure_kpa:.3f} kPa is outside the "
                f"plausible {lowest / PASCAL_PER_KILOPASCAL:.0f}-"
                f"{highest / PASCAL_PER_KILOPASCAL:.0f} kPa range, so depth is "
                f"measured against {standard_kpa:.3f} kPa instead. If the ROV was "
                "powered on underwater, restart it at the surface to zero depth."
            )
            return SURFACE_PRESSURE_PA
        log_info(f"Surface pressure captured: {pressure_kpa:.3f} kPa.")
        return pressure_pa

    def _check_achievable_read_rate(self, sensor: Smp2000) -> None:
        """Warn if the sensor cannot keep up with the configured read frequency.

        The SMP2000 conversion time depends on the oversampling its start
        command selects. A sensor slower than the configured interval makes the
        loop run late and the depth derivative filter mistuned, which the depth
        hold D-term is sensitive to.

        Args:
            sensor: The initialized sensor to time.
        """
        try:
            slowest = sensor.measure_conversion_time()
        except Exception as e:
            log_error(f"Could not time SMP2000 conversions: {e}")
            return
        interval = 1.0 / PRESSURE_SENSOR_READ_FREQUENCY
        log_info(
            f"SMP2000 slowest measurement took {slowest * 1000:.1f} ms "
            f"({PRESSURE_SENSOR_READ_FREQUENCY} Hz needs {interval * 1000:.1f} ms)."
        )
        if slowest > interval:
            log_warn(
                f"SMP2000 cannot sustain {PRESSURE_SENSOR_READ_FREQUENCY} Hz. "
                "Depth hold will run slower than DEPTH_DERIVATIVE_EMA_TAU was "
                "tuned for."
            )

    def _schedule_reconnect(self) -> None:
        self._next_reconnect_time = (
            time.monotonic() + PRESSURE_SENSOR_RECONNECT_INTERVAL_S
        )

    def _reconnect_if_due(self) -> bool:
        """Periodically try to bring a disconnected sensor back.

        Returns whether the sensor is healthy again. Only the first failed
        attempt of an outage is logged.
        """
        if time.monotonic() < self._next_reconnect_time:
            return False
        self._schedule_reconnect()
        try:
            self._open_sensor()
        except Exception as e:
            if not self._reconnect_failure_logged:
                log_warn(
                    "SMP2000 pressure sensor is unavailable; retrying every "
                    f"{PRESSURE_SENSOR_RECONNECT_INTERVAL_S:.0f} s. Error: {e}"
                )
                self._reconnect_failure_logged = True
            return False
        self._reconnect_failure_logged = False
        self.state.system_health.pressure_sensor_healthy = True
        log_info("SMP2000 pressure sensor reconnected.")
        return True

    def _update_fluid_density(self) -> None:
        """Update the fluid density used for the depth calculation from config."""
        if self.state.rov_config.fluid_type == FluidType.SALTWATER:
            self.fluid_density = DENSITY_SALTWATER
        else:
            self.fluid_density = DENSITY_FRESHWATER
        self.current_fluid_type = self.state.rov_config.fluid_type

    def read_data(self) -> PressureData | None:
        """Read pressure data from the sensor.

        Reads absolute pressure and temperature from the SMP2000 and derives
        depth from the configured fluid density, relative to the surface
        pressure captured at startup. Units are pressure in mbar, temperature
        in °C, and depth in meters.

        Returns:
            PressureData if successful (containing pressure in mbar, temperature
            in °C, depth in m), None otherwise.
        """
        if self.sensor is None:
            return None
        try:
            measurement = self.sensor.measure()
            if measurement is None:
                return None
            pressure_pa = measurement.pressure_kpa * PASCAL_PER_KILOPASCAL
            depth = (pressure_pa - self.surface_pressure_pa) / (
                self.fluid_density * GRAVITY
            )
            return PressureData(
                pressure=measurement.pressure_kpa * MBAR_PER_KILOPASCAL,
                temperature=measurement.temperature_c,
                depth=depth,
            )
        except Exception as e:
            log_error(f"Error reading pressure sensor data: {e}")
            return None

    def _blocking_read_loop(self) -> None:
        """Pressure sensor read loop running in a dedicated background thread.

        Runs entirely outside the asyncio event loop so the read rate is not
        affected by event-loop callback latency. State writes are safe without
        a lock because CPython's GIL makes single object-reference assignments atomic.
        """
        failure_count = 0
        interval = 1.0 / PRESSURE_SENSOR_READ_FREQUENCY
        next_tick = time.perf_counter() + interval
        previous_depth: float = 0.0
        filtered_depth_change: float = 0.0
        previous_read_time: float = 0.0
        self._schedule_reconnect()
        while True:
            if self.state.rov_config.fluid_type != self.current_fluid_type:
                self._update_fluid_density()
            if (
                not self.state.system_health.pressure_sensor_healthy
                and not self._reconnect_if_due()
            ):
                time.sleep(1)
                next_tick = time.perf_counter() + interval
                continue
            try:
                data = self.read_data()
                if data:
                    now = time.perf_counter()
                    if previous_read_time > 0.0:
                        dt = now - previous_read_time
                        raw_depth_change = (data.depth - previous_depth) / dt
                        alpha = math.exp(-dt / DEPTH_DERIVATIVE_EMA_TAU)
                        filtered_depth_change = (
                            alpha * filtered_depth_change
                            + (1.0 - alpha) * raw_depth_change
                        )
                    previous_depth = data.depth
                    previous_read_time = now
                    data.depth_change = filtered_depth_change
                    data.sample_time = now
                    self.state.pressure = data
                    failure_count = 0
                else:
                    failure_count += 1
            except Exception as e:
                log_error(f"Pressure sensor read_loop error: {e}")
                failure_count += 1
            if failure_count >= SYSTEM_FAILURE_THRESHOLD:
                self.state.system_health.pressure_sensor_healthy = False
                failure_count = 0
                previous_read_time = 0.0
                self._schedule_reconnect()
                log_error(
                    "Pressure sensor failed 3 times, disabling pressure sensor until "
                    "it reconnects"
                )
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_tick += interval
            now = time.perf_counter()
            if next_tick < now:
                next_tick = now + interval

    async def read_loop(self) -> None:
        """Run the pressure sensor read loop in a dedicated background thread."""
        await asyncio.to_thread(self._blocking_read_loop)
