"""SMP2000 digital pressure sensor driver.

Protocol-level driver for the SMP2000 I2C pressure sensor. It knows nothing
about the ROV: give it the range the part was calibrated for and it returns
kilopascal and degrees Celsius, leaving depth, fluid density and health
reporting to the caller.

The frame layout and conversion formulas follow the vendor SMP3011
communication instruction, which the supplier confirms applies to this part.
A conversion is started by writing one command byte, not by the address-only
write the instruction describes:

    start     Write one command byte. 0xB0-0xB7 select the oversampling, from
              the highest (~225 ms per conversion) to the lowest (~16 ms).
    wait      The top two bits of byte 0 are a status field: 00 means the frame
              is valid, 01 means it is stale because the conversion is still
              running. Poll until those bits read 00.
    read      Six bytes: status, then a 24-bit bridge value MSB first in bytes
              1-3, then a 16-bit temperature value in bytes 4-5.

The bridge value reports a percentage of the digital range, with the calibrated
pressure span mapped onto a sub-range of it so there is headroom at both ends.

Measured on hardware against the supplier's command list: the supplier's
default 0xAC behaves exactly like 0xB0, and 0xB8-0xBF are both slower and
noisier than 0xB0-0xB7 at every step. The undocumented 0xA0 also starts a
conversion, but it reports pressure about 948 kPa off and no usable
temperature, so it must not be used.
"""

from collections.abc import Iterable
import contextlib
import time
from typing import Final, NamedTuple, cast

from smbus2 import SMBus, i2c_msg


SMP2000_I2C_ADDRESS: Final = 0x78
FRAME_SIZE: Final = 6

# 0xB3 converts in ~41 ms with ~1.2 mm (freshwater) of noise, measured on
# hardware, which leaves headroom for a 20 Hz read loop. Waiting out most of the
# conversion before polling keeps the busy-poll to a few bus reads per sample.
START_MEASUREMENT: Final = 0xB3
CONVERSION_WAIT_S: Final = 0.038
BUSY_POLL_INTERVAL_S: Final = 0.001
CONVERSION_TIMEOUT_S: Final = 0.5

STATUS_SHIFT: Final = 6
STATUS_VALID: Final = 0
STATUS_STALE: Final = 1
STATUS_COMMAND_MODE: Final = 2
STATUS_DIAGNOSTIC_FAULT: Final = 3

TEMPERATURE_FULL_SCALE: Final = 65536.0
TEMPERATURE_MIN_C: Final = -40.0
TEMPERATURE_MAX_C: Final = 150.0

TIMING_PROBE_SAMPLES: Final = 5


class Smp2000Calibration(NamedTuple):
    """Maps the sensor's raw counts onto engineering units.

    The part reports a fraction of its digital range, with the calibrated
    pressure span occupying a sub-range of it so there is headroom at both ends.
    """

    pressure_min_kpa: float
    pressure_max_kpa: float
    span_min_counts: int
    span_max_counts: int


class Smp2000Error(Exception):
    """Raised when the SMP2000 reports or triggers an unrecoverable condition."""


class Smp2000Frame(NamedTuple):
    """One six-byte response frame from the sensor."""

    status: int
    pressure_counts: int
    temperature_counts: int

    @property
    def valid(self) -> bool:
        """Whether this frame holds a freshly completed conversion."""
        return self.status == STATUS_VALID

    @property
    def stale(self) -> bool:
        """Whether the conversion behind this frame is still running."""
        return self.status == STATUS_STALE

    @property
    def fault(self) -> bool:
        """Whether the sensor is reporting a diagnostic fault."""
        return self.status == STATUS_DIAGNOSTIC_FAULT


class Smp2000Measurement(NamedTuple):
    """A converted pressure and temperature sample."""

    pressure_kpa: float
    temperature_c: float


class Smp2000:
    """SMP2000 pressure sensor on an I2C bus."""

    def __init__(
        self,
        calibration: Smp2000Calibration,
        bus_number: int = 1,
        address: int = SMP2000_I2C_ADDRESS,
    ):
        """Initialize the driver.

        Args:
            calibration: Range and span endpoints the part was calibrated for.
            bus_number: I2C bus number, matching /dev/i2c-<n>.
            address: 7-bit I2C address of the sensor.
        """
        self.calibration: Smp2000Calibration = calibration
        self.bus_number: int = bus_number
        self.address: int = address
        self._bus: SMBus | None = None

    def open(self) -> None:
        """Open the I2C bus and confirm the sensor completes a conversion.

        Raises:
            Smp2000Error: If the sensor does not produce a valid frame.
        """
        self.close()
        self._bus = SMBus(self.bus_number)
        frame = self._measure_frame()
        if frame is None:
            message = "SMP2000 did not complete a conversion within the timeout"
            raise Smp2000Error(message)
        if frame.fault:
            message = "SMP2000 reports a diagnostic fault"
            raise Smp2000Error(message)

    def close(self) -> None:
        """Close the I2C bus if it is open."""
        if self._bus is not None:
            with contextlib.suppress(OSError):
                self._bus.close()
            self._bus = None

    def read_frame(self) -> Smp2000Frame:
        """Read one six-byte response frame from the sensor.

        Returns:
            The status field and the raw 24-bit pressure and 16-bit temperature
            counts.

        Raises:
            Smp2000Error: If the bus is closed or the sensor returned short.
        """
        bus = self._require_bus()
        message = i2c_msg.read(self.address, FRAME_SIZE)
        bus.i2c_rdwr(message)
        # i2c_msg.__iter__ is a generator but smbus2 annotates its return type as
        # the yielded int, so the cast restores what it actually produces.
        data: list[int] = list(cast(Iterable[int], message))
        if len(data) != FRAME_SIZE:
            error = f"SMP2000 returned {len(data)} bytes, expected {FRAME_SIZE}"
            raise Smp2000Error(error)
        return Smp2000Frame(
            status=data[0] >> STATUS_SHIFT,
            pressure_counts=(data[1] << 16) | (data[2] << 8) | data[3],
            temperature_counts=(data[4] << 8) | data[5],
        )

    def measure(self) -> Smp2000Measurement | None:
        """Take one pressure and temperature measurement.

        Returns:
            The converted sample, or None if the sensor did not produce a valid
            frame before `CONVERSION_TIMEOUT_S`.
        """
        frame = self._measure_frame()
        if frame is None or not frame.valid:
            return None
        return Smp2000Measurement(
            pressure_kpa=self.to_kilopascal(frame.pressure_counts),
            temperature_c=to_celsius(frame.temperature_counts),
        )

    def measure_average(self, samples: int) -> float | None:
        """Average the pressure over several measurements.

        Measurements that fail are skipped rather than counted, so the result
        is the mean of however many succeeded.

        Args:
            samples: How many measurements to attempt.

        Returns:
            Mean pressure in kilopascal, or None if every measurement failed.
        """
        readings = [
            measurement.pressure_kpa
            for measurement in (self.measure() for _ in range(samples))
            if measurement is not None
        ]
        if not readings:
            return None
        return sum(readings) / len(readings)

    def measure_conversion_time(self, samples: int = TIMING_PROBE_SAMPLES) -> float:
        """Time a few complete measurement cycles.

        Args:
            samples: How many measurement cycles to time.

        Returns:
            The slowest cycle observed, in seconds.
        """
        slowest = 0.0
        for _ in range(samples):
            started = time.perf_counter()
            _ = self.measure()
            slowest = max(slowest, time.perf_counter() - started)
        return slowest

    def to_kilopascal(self, counts: int) -> float:
        """Convert a raw pressure count to kilopascal.

        Args:
            counts: Raw 24-bit pressure count from the sensor.

        Returns:
            Pressure in kilopascal.
        """
        cal = self.calibration
        span_counts = cal.span_max_counts - cal.span_min_counts
        ratio = (counts - cal.span_min_counts) / span_counts
        span_kpa = cal.pressure_max_kpa - cal.pressure_min_kpa
        return ratio * span_kpa + cal.pressure_min_kpa

    def _require_bus(self) -> SMBus:
        """Return the open bus.

        Returns:
            The open SMBus handle.

        Raises:
            Smp2000Error: If the bus has not been opened.
        """
        if self._bus is None:
            message = "SMP2000 I2C bus is not open"
            raise Smp2000Error(message)
        return self._bus

    def _start_measurement(self) -> None:
        """Begin a conversion."""
        bus = self._require_bus()
        bus.i2c_rdwr(i2c_msg.write(self.address, [START_MEASUREMENT]))

    def _measure_frame(self) -> Smp2000Frame | None:
        """Start a conversion and poll until the frame stops being stale.

        Returns:
            The first non-stale frame, or None on timeout.
        """
        self._start_measurement()
        deadline = time.perf_counter() + CONVERSION_TIMEOUT_S
        time.sleep(CONVERSION_WAIT_S)
        while True:
            frame = self.read_frame()
            if not frame.stale:
                return frame
            if time.perf_counter() >= deadline:
                return None
            time.sleep(BUSY_POLL_INTERVAL_S)


def to_celsius(counts: int) -> float:
    """Convert a raw 16-bit temperature count to degrees Celsius.

    Args:
        counts: Raw 16-bit temperature count from the sensor.

    Returns:
        Temperature in degrees Celsius.
    """
    ratio = counts / TEMPERATURE_FULL_SCALE
    return ratio * (TEMPERATURE_MAX_C - TEMPERATURE_MIN_C) + TEMPERATURE_MIN_C
