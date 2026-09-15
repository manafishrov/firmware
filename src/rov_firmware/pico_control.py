"""Pi orchestration only: smoothing, reliable commands and Pico state projection.

No AHRS, PID, allocation or motor correction runs here. The old implementation
remains a test oracle, never a fallback for incompatible or unavailable hardware.
"""

import asyncio
import contextlib
import math
import os
import secrets
import struct
import time
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial.transform import Rotation

from . import pico_protocol as wire
from .constants import THRUSTER_TEST_DURATION_SECONDS, THRUSTER_TEST_TOAST_ID
from .log import log_error, log_info
from .models.config import RovConfig
from .models.sensors import ImuData
from .models.toast import ToastVariant
from .toast import ToastContent, cancel_thruster_test_action, toast_content


if TYPE_CHECKING:
    from .rov_state import RovState
    from .serial import SerialManager

APPLY_TIMEOUT = 8.0
REQUEST_RETRY = 0.5
_COMMIT_ACK_ATTEMPTS = (
    14  # Allow the device's seven-second apply deadline before QUERY.
)
CONTROL_INTERVAL = 1 / 60
HOST_TIMEOUT = 0.2
TELEMETRY_TIMEOUT = 0.2
PRESSURE_TIMEOUT = 0.5
MAX_SEQUENCE = 0xFFFFFFFE
QUATERNION_SIZE = 4
MIN_QUATERNION_NORM = 1e-6
_NOT_READY = 5


class PicoControl:
    """One ordered host writer and a correlated, generation-aware receive endpoint."""

    def __init__(self, state: "RovState", serial: "SerialManager") -> None:
        """Create an inactive endpoint; negotiation precedes every extended write."""
        self.state = state
        self.serial = serial
        self._maintenance = False
        self._gate = asyncio.Lock()
        self._waiter: asyncio.Future[wire.Frame] | None = None
        self._pending: wire.Frame | None = None
        self._capability: asyncio.Future[wire.Frame] | None = None
        self._capability_id = 0
        self._generation = -1
        self.session = 0
        self._failed_session = 0
        self._sequence = 0
        self._settings_generation = 0
        self._settings_crc = 0
        self._ready = False
        self._negotiated = False
        self.capability_checked = False
        self.development_identity: str | None = None
        self._last_telemetry = 0.0
        self._last_telemetry_sequence = 0
        self._last_imu_sequence = 0
        self._last_raw_imu = 0.0
        self._last_source = 0.0
        self._previous_direction = np.zeros(8, dtype=np.float32)
        self._last_pressure: object | None = None
        self._last_pressure_health: bool | None = None
        self._test_request = -1
        self._last_error: str | None = None
        self._last_motor_commands = [1000] * 8
        self._last_stats: dict[str, int | float] = {}
        self.current_quaternion = (0.0, 0.0, 0.0, 1.0)
        self.desired_quaternion = (0.0, 0.0, 0.0, 1.0)

    @property
    def suppress_bundled_reconciliation(self) -> bool:
        """Explicit local development opt-out, never an arbitrary version bypass."""
        return (
            os.environ.get("MANAFISH_PICO_CONTROL_DEVELOPMENT") == "1"
            and self._generation == self.serial.connection_generation
            and self.development_identity is not None
        )

    def _unavailable(self, reason: str) -> None:
        self._ready = False
        self.state.system_status.thruster_control_ready = False
        self.state.system_status.thruster_protocol_state = "failed"
        self.state.system_status.thruster_protocol_error = reason
        if reason != self._last_error:
            log_error(reason)
            self._last_error = reason

    def _invalidate_session(self, reason: str) -> None:
        """A safety latch requires a different HELLO, not retries in the failed epoch."""
        self._failed_session = self.session or self._failed_session
        self.session = 0
        self._negotiated = False
        self._settings_generation = self._settings_crc = 0
        self.state.system_health.imu_healthy = False
        self._unavailable(reason)
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_exception(ConnectionError(reason))

    def _next_session(self) -> int:
        excluded = self._failed_session or self.session
        # Leave room to skip the safety-failed epoch without retrying random draws.
        candidate = secrets.randbelow(0xFFFFFFFE) + 1
        return candidate + int(excluded != 0 and candidate >= excluded)

    def _reset_connection(self) -> None:
        self._generation = self.serial.connection_generation
        self._failed_session = self.session or self._failed_session
        self.session = 0
        self._sequence = 0
        self._settings_generation = 0
        self._settings_crc = 0
        self._ready = False
        self._negotiated = False
        self.capability_checked = False
        self.development_identity = None
        self._last_telemetry = 0.0
        self._last_telemetry_sequence = 0
        self._last_imu_sequence = 0
        self._last_raw_imu = 0.0
        self._last_pressure = None
        self.state.system_health.imu_healthy = False
        self.state.system_status.thruster_control_ready = False
        for future in (self._waiter, self._capability):
            if future is not None and not future.done():
                future.set_exception(ConnectionError("Pico connection changed"))

    async def _write(self, packet: bytes) -> None:
        if self._generation != self.serial.connection_generation:
            msg = "Pico connection changed during request"
            raise ConnectionError(msg)
        if self.state.mcu_flashing:
            msg = "Motor firmware operation owns USB"
            raise ConnectionError(msg)
        async with self.serial.write_lock:
            writer = self.serial.get_writer()
            async with asyncio.timeout(HOST_TIMEOUT):
                writer.write(packet)
                await writer.drain()

    async def neutral(self) -> None:
        """Legacy neutral is safe before negotiation and preempts computed output."""
        if self._negotiated and not self._maintenance:
            await self._write(
                self._frame(wire.RAW_MOTORS, struct.pack("<8H", *([1000] * 8))).encode()
            )
            return
        packet = bytes([0x5A]) + struct.pack("<8H", *([1000] * 8))
        checksum = 0
        for value in packet:
            checksum ^= value
        await self._write(packet + bytes([checksum]))

    def _frame(self, kind: int, payload: bytes = b"") -> wire.Frame:
        if self._sequence >= MAX_SEQUENCE:
            self._negotiated = False
            self._unavailable("Pico sequence exhausted; reconnect required")
            msg = "Pico sequence exhausted"
            raise ConnectionError(msg)
        self._sequence += 1
        return wire.Frame(kind, self.session, self._sequence, payload)

    async def _request(
        self,
        kind: int,
        payload: bytes = b"",
        *,
        staged: bool = False,
        attempts: int | None = None,
    ) -> wire.Frame:
        frame = self._frame(kind, payload)
        self._pending = frame
        waiter = asyncio.get_running_loop().create_future()
        self._waiter = waiter
        attempt = 0
        try:
            while True:
                attempt += 1
                await self._write(frame.encode())
                try:
                    reply = await asyncio.wait_for(
                        asyncio.shield(waiter), REQUEST_RETRY
                    )
                    break
                except TimeoutError:
                    if attempts is not None and attempt >= attempts:
                        raise
                    continue
            request_type, result, reserved, _generation, _digest = struct.unpack(
                "<BBHII", reply.payload
            )
            if (
                request_type != kind
                or reserved != 0
                or result != (wire.STAGED if staged else wire.APPLIED)
            ):
                msg = f"Pico rejected request {kind:#x} (result {result})"
                raise RuntimeError(msg)
            return reply
        finally:
            if not waiter.done():
                waiter.cancel()
            self._waiter = None
            self._pending = None

    async def _negotiate(self) -> None:
        """Only fixed-size legacy C5 bytes reach old firmware before capability proof."""
        self._capability_id = self._capability_id % 255 + 1
        capability = asyncio.get_running_loop().create_future()
        self._capability = capability
        packet = bytes([0xC5, 3, self._capability_id, 0, 0, 0])
        checksum = 0
        for value in packet:
            checksum ^= value
        try:
            await self.neutral()
            info = bytes([0xC5, 2, self._capability_id, 0, 0, 0])
            info_checksum = 0
            for value in info:
                info_checksum ^= value
            await self._write(info + bytes([info_checksum]))
            for _ in range(3):
                await self._write(packet + bytes([checksum]))
                try:
                    reply = await asyncio.wait_for(
                        asyncio.shield(capability), REQUEST_RETRY
                    )
                    break
                except TimeoutError:
                    continue
            else:
                msg = "Pico control v1 capability unavailable; output remains neutral"
                raise RuntimeError(msg)
            if len(reply.payload) < wire.CAPABILITY_HEADER_SIZE:
                msg = "Truncated Pico capabilities"
                raise RuntimeError(msg)
            schema, maximum, size, nullspace, features = struct.unpack_from(
                "<HHHHI", reply.payload
            )
            if (
                schema != 1
                or maximum < wire.SETTINGS_SIZE + 4
                or size != wire.SETTINGS_SIZE
                or nullspace != wire.MAX_NULLSPACE
                or features & wire.REQUIRED_FEATURES != wire.REQUIRED_FEATURES
            ):
                msg = "Incompatible Pico control capabilities; output remains neutral"
                raise RuntimeError(msg)
            identity = reply.payload[12:].decode("ascii", errors="strict")
            if features & 16 and identity.startswith("pico-control-dev:"):
                self.development_identity = identity
            self.session = self._next_session()
            self._sequence = 0
            self._last_telemetry_sequence = 0
            self._last_imu_sequence = 0
            self._last_telemetry = self._last_raw_imu = 0.0
            self.state.system_health.imu_healthy = False
            await self._request(wire.HELLO)
            self._negotiated = True
            log_info(f"Pico control v1 negotiated: {identity}")
        finally:
            self.capability_checked = True
            if not capability.done():
                capability.cancel()
            self._capability = None

    async def _apply(self, image: bytes) -> None:
        self._ready = False
        self.state.system_status.thruster_control_ready = False
        self.state.system_status.thruster_protocol_state = "applying"
        await self.neutral()
        # Recover any abandoned staging image without guessing what a lost ACK meant.
        await self._request(wire.ABORT)
        active = await self._request(wire.QUERY)
        _, _, _, active_generation, _active_digest = struct.unpack(
            "<BBHII", active.payload
        )
        generation = active_generation + 1
        digest = wire.crc32c(image)
        await self._request(
            wire.BEGIN, struct.pack("<III", generation, len(image), digest), staged=True
        )
        await self._request(wire.CHUNK, struct.pack("<I", 0) + image, staged=True)
        try:
            reply = await self._request(
                wire.COMMIT,
                struct.pack("<II", generation, digest),
                attempts=_COMMIT_ACK_ATTEMPTS,
            )
        except TimeoutError:
            # A lost terminal ACK is recoverable only by querying this exact committed image.
            reply = await self._request(wire.QUERY)
        _, _, _, applied_generation, applied_digest = struct.unpack(
            "<BBHII", reply.payload
        )
        if (applied_generation, applied_digest) != (generation, digest):
            msg = "Pico acknowledged a different settings image"
            raise RuntimeError(msg)
        self._settings_generation = generation
        self._settings_crc = digest
        self._ready = True
        self._last_error = None
        self.state.system_status.thruster_protocol_state = "ready"
        self.state.system_status.thruster_protocol_error = None

    async def apply_config(self, config: RovConfig) -> None:
        """Return only after matching atomic protocol+math COMMIT APPLIED."""
        if self._maintenance or self.state.mcu_flashing:
            msg = "Motor maintenance is active"
            raise RuntimeError(msg)
        image = wire.settings_image(config)
        async with asyncio.timeout(APPLY_TIMEOUT):
            async with self._gate:
                if (
                    self._maintenance
                    or not self._negotiated
                    or self._generation != self.serial.connection_generation
                ):
                    msg = "Pico control is not negotiated"
                    raise ConnectionError(msg)
                try:
                    await self._apply(image)
                    # Persistence must finish before actuation resumes with this image.
                    self._ready = False
                except BaseException:
                    self._unavailable(
                        "Pico settings outcome unknown or rejected; output inhibited"
                    )
                    with contextlib.suppress(Exception):
                        await self.neutral()
                    raise

    async def enter_maintenance(self) -> None:
        """Close control authority before granting the existing ESC uploader USB."""
        self._maintenance = True
        self._ready = False
        self.state.system_status.thruster_control_ready = False
        async with asyncio.timeout(APPLY_TIMEOUT):
            async with self._gate:
                if self.session:
                    await self._write(
                        self._frame(
                            wire.RAW_MOTORS, struct.pack("<8H", *([1000] * 8))
                        ).encode()
                    )
                    await self._request(wire.ENTER_MAINTENANCE)
                else:
                    await self.neutral()
                self._negotiated = False
                self.session = 0

    def leave_maintenance(self) -> None:
        """Release the host latch; fresh HELLO/settings/input are still mandatory."""
        self._negotiated = False
        self._ready = False
        self.session = 0
        self._last_pressure = None
        self._maintenance = False

    def confirm_persisted_config(self) -> None:
        """Resume only after the host has persisted the acknowledged image."""
        self._ready = True

    async def _set_target(self, kind: int, payload: bytes) -> None:
        async with asyncio.timeout(APPLY_TIMEOUT):
            async with self._gate:
                if not self._ready:
                    msg = "Pico control is not ready"
                    raise ConnectionError(msg)
                try:
                    await self._request(kind, payload)
                except BaseException:
                    self._unavailable(
                        "Pico target outcome unknown or rejected; output inhibited"
                    )
                    with contextlib.suppress(Exception):
                        await self.neutral()
                    raise

    async def set_desired_attitude(
        self, quaternion: tuple[float, float, float, float]
    ) -> None:
        """Apply absolute body-to-world [x,y,z,w], without enabling/resetting PID."""
        if len(quaternion) != QUATERNION_SIZE or not all(
            math.isfinite(value) for value in quaternion
        ):
            msg = "Desired quaternion must have four finite components"
            raise ValueError(msg)
        norm = math.sqrt(sum(value * value for value in quaternion))
        if norm < MIN_QUATERNION_NORM:
            msg = "Desired quaternion has zero norm"
            raise ValueError(msg)
        await self._set_target(
            wire.SET_ATTITUDE,
            struct.pack("<4f", *(value / norm for value in quaternion)),
        )

    async def set_desired_depth(self, depth: float) -> None:
        """Apply the pending/active depth target through the same ordered command stream."""
        if not math.isfinite(depth):
            msg = "Desired depth must be finite"
            raise ValueError(msg)
        await self._set_target(wire.SET_DEPTH, struct.pack("<f", max(0.0, depth)))

    def receive(self, frame: wire.Frame) -> None:
        """Called only by the sole USB parser, after length and CRC validation."""
        if self._generation != self.serial.connection_generation:
            return
        if frame.kind == wire.CAPABILITIES:
            future = self._capability
            if (
                frame.session == 0
                and frame.sequence == self._capability_id
                and future is not None
                and not future.done()
            ):
                future.set_result(frame)
            return
        if not self.session or frame.session != self.session:
            return
        if frame.kind == wire.ACK:
            self._ack(frame)
            return
        if frame.kind == wire.ATTITUDE:
            self._attitude(frame)
        elif frame.kind == wire.IMU:
            self._imu(frame)
        elif frame.kind == wire.STATS and len(frame.payload) == wire.STATS_SIZE:
            (
                elapsed,
                ahrs,
                pid,
                depth,
                missed,
                average,
                maximum,
                errors,
                overflows,
                host_age,
                output_age,
            ) = struct.unpack("<Q10I", frame.payload)
            self._last_stats = {
                "elapsed_us": elapsed,
                "completed_ahrs": ahrs,
                "completed_pid": pid,
                "completed_depth": depth,
                "missed_deadlines": missed,
                "average_execution_us": average,
                "max_execution_us": maximum,
                "sensor_errors": errors,
                "command_queue_overflows": overflows,
                "max_host_age_us": host_age,
                "max_output_age_us": output_age,
            }
            # Device emits the corresponding INFO record through the existing log path.

    def _ack(self, frame: wire.Frame) -> None:
        if len(frame.payload) != wire.ACK_SIZE:
            return
        if frame.payload[1] == _NOT_READY or (
            frame.payload[0] in (wire.CONTROL, wire.PRESSURE, wire.RAW_MOTORS)
            and frame.payload[1] != wire.APPLIED
        ):
            self._invalidate_session(
                f"Pico rejected command {frame.payload[0]:#x} (result {frame.payload[1]}); new session required"
            )
            return
        pending = self._pending
        waiter = self._waiter
        if (
            pending is not None
            and waiter is not None
            and not waiter.done()
            and frame.sequence == pending.sequence
            and frame.payload[0] == pending.kind
        ):
            waiter.set_result(frame)

    def _attitude(self, frame: wire.Frame) -> None:
        if (
            len(frame.payload) != wire.ATTITUDE_SIZE
            or frame.sequence <= self._last_telemetry_sequence
        ):
            return
        values = struct.unpack("<Q9f5I8HI", frame.payload)
        current = values[1:5]
        desired = values[5:9]
        depth = values[9]
        generation, _control_sequence, health, _host_age, _output_age = values[10:15]
        if generation != self._settings_generation or not all(
            math.isfinite(value) for value in (*current, *desired, depth)
        ):
            return
        if (
            min(
                sum(value * value for value in current),
                sum(value * value for value in desired),
            )
            < MIN_QUATERNION_NORM**2
        ):
            return
        self.current_quaternion = tuple(current)
        self.desired_quaternion = tuple(desired)
        yaw, pitch, roll = Rotation.from_quat(current).as_euler("ZYX", degrees=True)
        desired_yaw, desired_pitch, desired_roll = Rotation.from_quat(desired).as_euler(
            "ZYX", degrees=True
        )
        regulator = self.state.regulator
        regulator.yaw, regulator.pitch, regulator.roll = yaw, pitch, roll
        regulator.desired_yaw = desired_yaw
        # Preserve disabled UI projection; the internal target itself is retained.
        regulator.desired_pitch = (
            desired_pitch if self.state.system_status.auto_stabilization else 0.0
        )
        regulator.desired_roll = (
            desired_roll if self.state.system_status.auto_stabilization else 0.0
        )
        regulator.desired_depth = depth
        self.state.system_health.imu_healthy = bool(health & 1)
        self.state.thrusters.work_indicator_percentage = (
            0 if health & 8 else min(100, values[-1])
        )
        self._last_motor_commands = list(values[15:23])
        self._last_telemetry = time.monotonic()
        self._last_telemetry_sequence = frame.sequence
        self.state.system_status.thruster_control_ready = (
            self._ready
            and not self.state.mcu_flashing
            and not self.state.esc_firmware_recovery_required
        )

    def _imu(self, frame: wire.Frame) -> None:
        if (
            len(frame.payload) != wire.IMU_SIZE
            or frame.sequence <= self._last_imu_sequence
        ):
            return
        values = struct.unpack("<7f", frame.payload)
        if not all(math.isfinite(value) for value in values):
            return
        self.state.imu = ImuData(
            acceleration=np.array(values[:3], dtype=np.float32),
            gyroscope=np.array(values[3:6], dtype=np.float32),
            temperature=values[6],
        )
        self._last_raw_imu = time.monotonic()
        self._last_imu_sequence = frame.sequence

    def _expire_health(self, now: float) -> None:
        if (
            now - self._last_telemetry > TELEMETRY_TIMEOUT
            or now - self._last_raw_imu > TELEMETRY_TIMEOUT
        ):
            self.state.system_health.imu_healthy = False
            self.state.system_status.thruster_control_ready = False

    async def _send_pressure(self) -> None:
        pressure = self.state.pressure
        healthy = (
            self.state.system_health.pressure_sensor_healthy
            and pressure.sample_time > 0
            and time.monotonic() - pressure.sample_time < PRESSURE_TIMEOUT
        )
        if pressure is self._last_pressure and healthy == self._last_pressure_health:
            return
        depth, change = pressure.depth, pressure.depth_change
        if not math.isfinite(depth) or not math.isfinite(change):
            healthy = False
            depth = change = 0.0
        await self._write(
            self._frame(
                wire.PRESSURE, struct.pack("<ffI", depth, change, int(healthy))
            ).encode()
        )
        self._last_pressure = pressure
        self._last_pressure_health = healthy

    async def _send_direction(self, now: float) -> None:
        state = self.state
        raw = state.thrusters.direction_vector
        valid = (
            raw is not None
            and state.thrusters.last_direction_time > 0
            and 0 <= time.time() - state.thrusters.last_direction_time < HOST_TIMEOUT
        )
        direction = (
            np.zeros(8, dtype=np.float32)
            if not valid
            else np.array(raw, dtype=np.float32)
        )
        if not np.all(np.isfinite(direction)) or np.any(np.abs(direction) > 1):
            valid = False
            direction.fill(0)
        source_dt = (
            min(1 / 6, max(1 / 120, now - self._last_source))
            if self._last_source
            else CONTROL_INTERVAL
        )
        self._last_source = now
        if valid:
            smoothing = state.rov_config.smoothing_factor
            if smoothing > CONTROL_INTERVAL:
                step = CONTROL_INTERVAL / smoothing
                direction = self._previous_direction + np.clip(
                    direction - self._previous_direction, -step, step
                )
            self._previous_direction[:] = direction
        flags = (
            int(state.system_status.auto_stabilization)
            | (int(state.system_status.depth_hold) << 1)
            | (int(valid) << 2)
        )
        await self._write(
            self._frame(
                wire.CONTROL, struct.pack("<9fI", *direction.tolist(), source_dt, flags)
            ).encode()
        )

    async def cancel_thruster_test(self) -> None:
        """Issue an explicit neutral barrier before ordinary pilot control resumes."""
        async with self._gate:
            await self.neutral()

    def _end_test(self, variant: ToastVariant, key: str) -> None:
        self.state.thrusters.test_thruster = None
        self.state.thrusters.test_start_time = None
        self.state.thrusters.last_remaining = 0
        toast_content(
            identifier=THRUSTER_TEST_TOAST_ID,
            variant=variant,
            content=ToastContent(message_key=key),
            action=None,
        )

    async def _send_test(self) -> bool:
        thrusters = self.state.thrusters
        index = thrusters.test_thruster
        if index is None:
            return False
        if index not in range(8) or not self.state.system_status.thruster_control_ready:
            self._end_test(ToastVariant.ERROR, "toasts_thruster_test_unavailable")
            await self.neutral()
            return True
        now = time.time()
        if thrusters.test_start_time is not None and now < thrusters.test_start_time:
            self._end_test(ToastVariant.ERROR, "toasts_thruster_test_unavailable")
            await self.neutral()
            return True
        if (
            thrusters.test_start_time is not None
            and now - thrusters.test_start_time >= THRUSTER_TEST_DURATION_SECONDS
        ):
            await self.neutral()
            self._end_test(ToastVariant.SUCCESS, "toasts_thruster_test_completed")
            return True
        request = thrusters.test_request_id
        thrusters.work_indicator_percentage = 0
        motors = [1000] * 8
        motors[index] = 1100
        await self._write(
            self._frame(wire.RAW_MOTORS, struct.pack("<8H", *motors)).encode()
        )
        if request != thrusters.test_request_id or thrusters.test_thruster != index:
            return True
        self._test_request = request
        if thrusters.test_start_time is None:
            thrusters.test_start_time = time.time()
        remaining = math.ceil(10 - (time.time() - thrusters.test_start_time))
        if remaining != thrusters.last_remaining:
            thrusters.last_remaining = remaining
            toast_content(
                identifier=THRUSTER_TEST_TOAST_ID,
                variant=ToastVariant.LOADING,
                content=ToastContent(
                    message_key="toasts_thruster_test_title",
                    message_args={"thruster": index},
                    description_key="toasts_seconds_remaining",
                    description_args={"seconds": remaining},
                ),
                action=cancel_thruster_test_action(index),
            )
        return True

    def diagnostic_snapshot(self, now: float) -> dict[str, object]:
        """Measured device state, never host write counts presented as executions."""
        return {
            "pico_session": self.session,
            "settings_generation": self._settings_generation,
            "last_motors": self._last_motor_commands,
            "stats": self._last_stats,
            "attitude_age_s": now - self._last_telemetry,
            "development_identity": self.development_identity,
        }

    async def send_loop(self) -> None:  # noqa: C901, PLR0912 - safety exits precede all stream writes
        """Maintain a 60Hz smoothed source stream without catch-up bursts."""
        next_tick = time.monotonic()
        while True:
            try:
                if not await self.serial.ensure_connection():
                    self._unavailable("Pico USB unavailable; output inhibited")
                    await asyncio.sleep(1)
                    continue
                if self._generation != self.serial.connection_generation:
                    self._reset_connection()
                if (
                    self._maintenance
                    or self.state.mcu_flashing
                    or self.state.esc_firmware_recovery_required
                ):
                    self._ready = False
                    self._negotiated = False
                    self.state.system_status.thruster_control_ready = False
                    if self.state.thrusters.test_thruster is not None:
                        self._end_test(
                            ToastVariant.ERROR, "toasts_thruster_test_unavailable"
                        )
                    await asyncio.sleep(CONTROL_INTERVAL)
                    continue
                async with self._gate:
                    if not self._negotiated:
                        async with asyncio.timeout(APPLY_TIMEOUT):
                            await self._negotiate()
                            await self._apply(
                                wire.settings_image(self.state.rov_config)
                            )
                    self._expire_health(time.monotonic())
                    if not self._ready:
                        await self.neutral()
                    else:
                        await self._send_pressure()
                        if not await self._send_test():
                            await self._send_direction(time.monotonic())
                next_tick += CONTROL_INTERVAL
                now = time.monotonic()
                if next_tick < now:
                    next_tick = now + CONTROL_INTERVAL
                await asyncio.sleep(next_tick - now)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._unavailable(f"Pico control unavailable: {error}")
                self.state.system_health.imu_healthy = False
                with contextlib.suppress(Exception):
                    await self.neutral()
                if self.state.thrusters.test_thruster is not None:
                    self._end_test(
                        ToastVariant.ERROR, "toasts_thruster_test_unavailable"
                    )
                await asyncio.sleep(1)
