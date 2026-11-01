"""Publish extra Raspberry Pi, firmware and raw sensor readings for diagnostics.

Installed disabled by default: enable it in Custom actions, then add the readings
you need in Appearance. Sampling runs while an app is connected and stops on
disconnect. These values are rarely needed while driving; they help with specific
needs such as checking CPU load, overheating, network throughput, firmware
responsiveness, raw IMU and pressure data, or per-ESC telemetry. Unhealthy
sensors are reported as unavailable instead of showing their last values.
"""

import asyncio
import os
from pathlib import Path
import time
from typing import ClassVar

import psutil
from pydantic import BaseModel, ConfigDict

from manafish_sdk import Context, Reading, Script, Widget


SAMPLE_INTERVAL_SECONDS = 1.0
CPU_TEMPERATURE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
DISK_PATH = Path.home()
MEBIBYTE = 1024 * 1024

script = Script(
    "extended_telemetry",
    name="Extended telemetry",
    description="Extra Pi, firmware and raw sensor readings for diagnostics.",
)


def _reading[T](
    identifier: str, value_type: type[T], name: str, unit: str | None = None
) -> Reading[T]:
    return script.reading(
        identifier,
        value_type,
        name=name,
        unit=unit,
        widget=Widget.TEXT,
        stale_after=SAMPLE_INTERVAL_SECONDS * 3,
    )


cpu_usage = _reading("cpu_usage", float, "Pi CPU usage", "%")
cpu_core_usage = _reading("cpu_core_usage", list[float], "Pi CPU core usage", "%")
cpu_temperature = _reading("cpu_temperature", float, "Pi CPU temperature", "°C")
cpu_frequency = _reading("cpu_frequency", float, "Pi CPU frequency", "MHz")
load_average = _reading("load_average", float, "Pi load average (1 min)")
memory_usage = _reading("memory_usage", float, "Pi memory usage", "%")
memory_available = _reading("memory_available", float, "Pi memory available", "MiB")
disk_usage = _reading("disk_usage", float, "Pi storage usage", "%")
uptime = _reading("uptime", float, "Pi uptime", "h")
network_received = _reading("network_received", float, "Network received", "kB/s")
network_sent = _reading("network_sent", float, "Network sent", "kB/s")
firmware_cpu = _reading("firmware_cpu", float, "Firmware CPU usage", "%")
firmware_memory = _reading("firmware_memory", float, "Firmware memory", "MiB")
event_loop_lag = _reading("event_loop_lag", float, "Firmware event loop lag", "ms")
imu_acceleration = _reading("imu_acceleration", list[float], "IMU acceleration", "m/s²")
imu_angular_velocity = _reading(
    "imu_angular_velocity", list[float], "IMU angular velocity", "rad/s"
)
imu_temperature = _reading("imu_temperature", float, "IMU temperature", "°C")
pressure = _reading("pressure", float, "Raw pressure", "mbar")
depth_rate = _reading("depth_rate", float, "Depth rate", "m/s")
esc_voltages = _reading("esc_voltages", list[float], "ESC voltages", "V")
esc_temperatures = _reading("esc_temperatures", list[float], "ESC temperatures", "°C")
esc_currents = _reading("esc_currents", list[float], "ESC raw currents", "A")
esc_erpm = _reading("esc_erpm", list[float], "ESC electrical RPM", "eRPM")


class SystemSample(BaseModel):
    """Pi and firmware process measurements read off the event loop."""

    cpu_usage: float
    cpu_core_usage: list[float]
    cpu_temperature: float | None
    cpu_frequency: float | None
    load_average: float
    memory_usage: float
    memory_available: float
    disk_usage: float
    uptime: float
    network_bytes: tuple[int, int]
    firmware_cpu: float
    firmware_memory: float


class NetworkState(BaseModel):
    """Remember the previous counters to turn totals into rates."""

    model_config: ClassVar[ConfigDict] = ConfigDict(validate_assignment=True)

    received: int = 0
    sent: int = 0
    sampled_at: float | None = None


def _cpu_temperature() -> float | None:
    try:
        return int(CPU_TEMPERATURE_PATH.read_text()) / 1000
    except (OSError, ValueError):
        return None


def _read_system(process: psutil.Process) -> SystemSample:
    """CPU percentages cover the time since the previous call."""
    frequency = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    counters = psutil.net_io_counters(pernic=True)
    interfaces = [stats for name, stats in counters.items() if name != "lo"]
    return SystemSample(
        cpu_usage=psutil.cpu_percent(),
        cpu_core_usage=psutil.cpu_percent(percpu=True),
        cpu_temperature=_cpu_temperature(),
        cpu_frequency=frequency.current if frequency else None,
        load_average=os.getloadavg()[0],
        memory_usage=memory.percent,
        memory_available=memory.available / MEBIBYTE,
        disk_usage=psutil.disk_usage(str(DISK_PATH)).percent,
        uptime=(time.time() - psutil.boot_time()) / 3600,
        network_bytes=(
            sum(stats.bytes_recv for stats in interfaces),
            sum(stats.bytes_sent for stats in interfaces),
        ),
        firmware_cpu=process.cpu_percent(),
        firmware_memory=process.memory_info().rss / MEBIBYTE,
    )


async def _in_thread(process: psutil.Process) -> SystemSample:
    """Let the read finish before cancellation completes; threads cannot be stopped."""
    read = asyncio.create_task(asyncio.to_thread(_read_system, process))
    try:
        return await asyncio.shield(read)
    except asyncio.CancelledError:
        await read
        raise


async def _publish_system(sample: SystemSample, network: NetworkState) -> None:
    await cpu_usage.publish(sample.cpu_usage)
    await cpu_core_usage.publish(sample.cpu_core_usage)
    await cpu_temperature.publish(sample.cpu_temperature)
    await cpu_frequency.publish(sample.cpu_frequency)
    await load_average.publish(sample.load_average)
    await memory_usage.publish(sample.memory_usage)
    await memory_available.publish(sample.memory_available)
    await disk_usage.publish(sample.disk_usage)
    await uptime.publish(sample.uptime)
    await firmware_cpu.publish(sample.firmware_cpu)
    await firmware_memory.publish(sample.firmware_memory)

    now = time.monotonic()
    received, sent = sample.network_bytes
    if network.sampled_at is not None:
        elapsed = now - network.sampled_at
        await network_received.publish((received - network.received) / elapsed / 1000)
        await network_sent.publish((sent - network.sent) / elapsed / 1000)
    network.received, network.sent, network.sampled_at = received, sent, now


async def _publish_sensors(ctx: Context) -> None:
    """Report unavailable sensors as None rather than stale or default values."""
    health = ctx.rov.system_health
    imu = ctx.rov.imu if health.imu_healthy else None
    await imu_acceleration.publish(None if imu is None else imu.acceleration.tolist())
    await imu_angular_velocity.publish(None if imu is None else imu.gyroscope.tolist())
    await imu_temperature.publish(None if imu is None else imu.temperature)

    water = ctx.rov.pressure if health.pressure_sensor_healthy else None
    await pressure.publish(None if water is None else water.pressure)
    await depth_rate.publish(None if water is None else water.depth_change)

    mcu = ctx.rov.mcu_telemetry if health.mcu_healthy else None
    await esc_voltages.publish(None if mcu is None else mcu.voltage)
    await esc_temperatures.publish(
        None if mcu is None else [float(value) for value in mcu.temperature]
    )
    await esc_currents.publish(
        None if mcu is None else [float(value) for value in mcu.current]
    )
    await esc_erpm.publish(
        None if mcu is None else [float(value) for value in mcu.erpm]
    )


@script.background()
async def sample(ctx: Context) -> None:
    """Sample once per interval while an app is connected."""
    loop = asyncio.get_running_loop()
    process = psutil.Process()
    network = NetworkState()
    # The first CPU percentages only start the measurement window.
    await _in_thread(process)
    while True:
        started = loop.time()
        await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
        lag = loop.time() - started - SAMPLE_INTERVAL_SECONDS
        await event_loop_lag.publish(max(0.0, lag * 1000))
        await _publish_system(await _in_thread(process), network)
        await _publish_sensors(ctx)
