#!/usr/bin/env python3
"""Opt-in, disconnected-ESC acceptance of the actual Pi/Pico stack.

No port is opened without --execute, --service-stopped, --escs-disconnected and
MANAFISH_PICO_CONTROL_DEVELOPMENT=1. Run with the staged firmware Python import
path and the Pi's real runtime dependencies. This does not upload any firmware.
The pressure thread is process-owned because the production read loop has no
stop primitive; main exits only after bounded neutral/restore/USB cleanup.
"""

import argparse
import asyncio
from collections import Counter
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import threading
import time
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation

from rov_firmware import esc_recovery, pico_protocol as wire
from rov_firmware.models.actions import DirectionVector
from rov_firmware.models.config import PartialRovConfig, RovConfig
from rov_firmware.pico_control import PicoControl
from rov_firmware.rov_state import RovState
from rov_firmware.sensors.mcu import McuSensor
from rov_firmware.sensors.pressure import PressureSensor
from rov_firmware.serial import SerialManager
from rov_firmware.websocket.message import Config, ShowToast
from rov_firmware.websocket.queue import get_message_queue
from rov_firmware.websocket.receive.actions import (
    handle_cancel_thruster_test,
    handle_direction_vector,
    handle_start_thruster_test,
)
from rov_firmware.websocket.receive.config import (
    handle_confirm_config,
    handle_set_config,
)
from rov_firmware.websocket.receive.state import handle_set_auto_stabilization
from rov_firmware.websocket.state import websocket_state


START_TIMEOUT = 15.0
STEP_TIMEOUT = 5.0
LEASE_WAIT = 0.35
RATE_LIMITS = {
    "pressure_hz": (13, 17),
    "telemetry_hz": (55, 65),
    "control_write_hz": (55, 65),
}
CONTROL_RATE_LIMITS = (475, 525)
ANGLE_TOLERANCE = 0.0002  # Below one 60 Hz command increment at the test yaw rate.
SMOOTHING_ZERO_TOLERANCE = 1e-5
DURATION_RANGE = (12, 30)
DEADLINE_RANGE = (60, 300)


class AcceptanceError(RuntimeError):
    """A measured acceptance condition failed; never replace it with simulated proof."""


def require(condition: bool, description: str) -> None:
    """Fail with a portable explanation in the final JSON."""
    if not condition:
        raise AcceptanceError(description)


class NoFlashSerial(SerialManager):
    """Real serial transport, with an explicit port and automatic ROM flashing disabled."""

    def __init__(self, state: RovState, port: str) -> None:
        """Select only the coordinator-specified USB port."""
        super().__init__(state)
        self.port = port

    async def _find_mcu_port(self, *, log_missing: bool = True) -> str | None:
        del log_missing
        return self.port if Path(self.port).exists() else None

    async def _auto_flash_first_boot(self) -> None:
        self._first_boot_flashed = True
        # The test must never turn a missing port into a firmware installation.


class NoFlashMcu(McuSensor):
    """Real parser/state projection; disable ONLY the automatic release installer."""

    def _auto_update_mcu_if_needed(
        self, current_version: str, expected_version: str | None
    ) -> None:
        del current_version, expected_version
        # No override of packet validation, ACKs, telemetry or control behavior.


class ObservedControl(PicoControl):
    """Real client with an identity guard and passive observations, never fabricated ACKs."""

    def __init__(
        self, state: RovState, serial: SerialManager, expected_identity: str
    ) -> None:
        """Initialize passive observations and the coordinator-specified identity guard."""
        super().__init__(state, serial)
        self.expected_identity = expected_identity
        self.received: Counter[int] = Counter()
        self.commands: list[tuple[float, wire.Frame]] = []
        self.acks: list[tuple[float, wire.Frame]] = []
        self.statistics: list[dict[str, Any]] = []
        self.attitude: dict[str, Any] = {}

    async def _negotiate(self) -> None:
        await super()._negotiate()
        if self.development_identity != self.expected_identity:
            self._negotiated = False
            msg = "Unexpected Pico build identity; refusing settings or motor commands"
            raise AcceptanceError(msg)

    async def _write(self, packet: bytes) -> None:
        await super()._write(packet)
        if packet[0] == wire.START:
            frame = wire.decode(packet)
            if frame.kind == wire.CONTROL:
                self.commands.append((time.monotonic(), frame))

    def receive(self, frame: wire.Frame) -> None:
        """Observe already-validated real frames without changing dispatch results."""
        current_session = self.session
        previous = self._last_telemetry
        super().receive(frame)
        if not current_session or frame.session != current_session:
            return
        now = time.monotonic()
        if frame.kind == wire.ACK and len(frame.payload) == wire.ACK_SIZE:
            self.acks.append((now, frame))
        if frame.kind == wire.ATTITUDE and self._last_telemetry != previous:
            self.received[frame.kind] += 1
            self.attitude = {
                "received_at": now,
                "last_control_sequence": struct.unpack_from("<I", frame.payload, 48)[0],
                "health": struct.unpack_from("<I", frame.payload, 52)[0],
                "host_age_us": struct.unpack_from("<I", frame.payload, 56)[0],
                "motors": list(struct.unpack_from("<8H", frame.payload, 64)),
            }
        if frame.kind == wire.STATS and len(frame.payload) == wire.STATS_SIZE:
            self.statistics.append({"received_at": now, **self._last_stats})


@dataclass
class Harness:
    """Run scenarios against actual hardware with staged-only persistent state."""

    state: RovState
    control: ObservedControl
    staged: Path
    baseline: RovConfig
    identity: str
    duration: float
    report: dict[str, Any]
    pilot_active: bool = True
    pilot: np.ndarray = field(default_factory=lambda: np.zeros(8, dtype=np.float32))
    messages: list[tuple[float, object, bool]] = field(default_factory=list)
    pressure_samples: int = 0

    async def wait(
        self,
        predicate: Callable[[], bool],
        description: str,
        timeout: float = STEP_TIMEOUT,
    ) -> None:
        """Bound every observation; propagate task failures rather than claim unavailable proof."""
        try:
            async with asyncio.timeout(timeout):
                while not predicate():
                    await asyncio.sleep(0.005)
        except TimeoutError as error:
            raise AcceptanceError(description) from error

    async def pilot_loop(self) -> None:
        """Exercise the real direction handler at the retained operator cadence."""
        next_tick = time.monotonic()
        while True:
            if self.pilot_active:
                await handle_direction_vector(
                    self.state, DirectionVector(root=self.pilot.copy())
                )
            next_tick += 1 / 60
            now = time.monotonic()
            next_tick = max(next_tick, now)
            await asyncio.sleep(next_tick - now)

    async def observations(self) -> None:
        """Count real pressure publications and consume actual outbound message objects."""
        previous_sample = 0.0
        queue = get_message_queue()
        while True:
            sample = self.state.pressure.sample_time
            if sample and sample != previous_sample:
                self.pressure_samples += 1
                previous_sample = sample
            while not queue.empty():
                message = queue.get_nowait()
                persisted = False
                if isinstance(message, Config):
                    persisted = json.loads(self.staged.read_text()) == json.loads(
                        message.payload.config.model_dump_json(by_alias=True)
                    )
                self.messages.append((time.monotonic(), message, persisted))
            await asyncio.sleep(0.002)

    async def ready(self) -> None:
        """Require the exact expected development identity plus live sensors/readiness."""
        await self.wait(
            lambda: (
                self.state.system_status.thruster_control_ready
                and self.state.system_health.imu_healthy
                and self.state.system_health.pressure_sensor_healthy
                and self.state.pressure.sample_time > 0
                and all(
                    math.isfinite(value)
                    for value in (
                        self.state.pressure.depth,
                        self.state.pressure.depth_change,
                        self.state.pressure.temperature,
                    )
                )
            ),
            "No ready control session with real finite IMU/pressure publications",
            START_TIMEOUT,
        )
        require(
            self.control.development_identity == self.identity,
            "Unexpected Pico development build identity",
        )
        require(
            self.control.suppress_bundled_reconciliation,
            "Development identity/environment guard was not verified",
        )
        self.report["identity"] = {
            "build": self.control.development_identity,
            "session": self.control.session,
            "usb_generation": self.control.serial.connection_generation,
            "release": self.state.device_info.mcu_firmware_version,
        }

    async def cadence(self) -> None:
        """Measure host publication cadence and complete device control windows independently."""
        await handle_set_auto_stabilization(self.state, True)
        start = time.monotonic()
        pressure, telemetry, commands = (
            self.pressure_samples,
            self.control.received[wire.ATTITUDE],
            len(self.control.commands),
        )
        await asyncio.sleep(self.duration)
        elapsed = time.monotonic() - start
        rates = {
            "elapsed_s": elapsed,
            "pressure_hz": (self.pressure_samples - pressure) / elapsed,
            "telemetry_hz": (self.control.received[wire.ATTITUDE] - telemetry)
            / elapsed,
            "control_write_hz": (len(self.control.commands) - commands) / elapsed,
        }
        windows = [
            item
            for item in self.control.statistics
            if item["received_at"] - item["elapsed_us"] / 1e6 >= start
        ]
        self.report["cadence"] = {**rates, "device_windows": windows}
        self.report["sensor_readback"] = {
            "pressure": json.loads(self.state.pressure.model_dump_json()),
            "imu": json.loads(self.state.imu.model_dump_json()),
            "actual_xyzw": list(self.control.current_quaternion),
            "desired_xyzw": list(self.control.desired_quaternion),
        }
        require(
            self.state.system_health.pressure_sensor_healthy
            and self.state.system_health.imu_healthy,
            "Sensor health failed during cadence measurement",
        )
        require(
            all(
                math.isfinite(value)
                for value in (
                    self.state.pressure.depth,
                    self.state.pressure.depth_change,
                    self.state.pressure.temperature,
                )
            ),
            "Pressure returned nonfinite data during cadence measurement",
        )
        for name, (low, high) in RATE_LIMITS.items():
            require(
                low <= rates[name] <= high, f"Measured {name} outside [{low},{high}]"
            )
        require(
            bool(windows),
            "No complete device statistics window inside the active control measurement",
        )
        for item in windows:
            duration = item["elapsed_us"] / 1e6
            require(duration > 0, "Invalid device statistics duration")
            for counter in ("completed_ahrs", "completed_pid"):
                hz = item[counter] / duration
                require(
                    CONTROL_RATE_LIMITS[0] <= hz <= CONTROL_RATE_LIMITS[1],
                    f"Measured {counter} rate {hz:.2f} is not approximately 500 Hz",
                )

    async def targets(self) -> None:
        """Set an absolute target while already enabled, then integrate actual sent input."""
        require(
            self.state.system_status.auto_stabilization,
            "Target test requires an already-enabled regulator",
        )
        initial = Rotation.from_quat(self.control.desired_quaternion)
        target = Rotation.from_rotvec([0, 0, math.radians(5)]) * initial
        x, y, z, w = (float(value) for value in target.as_quat())
        await self.state.set_desired_attitude((x, y, z, w))
        await self.wait(
            lambda: (
                (
                    target.inv() * Rotation.from_quat(self.control.desired_quaternion)
                ).magnitude()
                < ANGLE_TOLERANCE
            ),
            "Applied absolute target did not appear in telemetry",
        )
        start = len(self.control.commands)
        before = Rotation.from_quat(self.control.desired_quaternion)
        self.pilot[4] = 0.05
        await asyncio.sleep(0.4)
        self.pilot.fill(0)
        await self.wait(
            lambda: (
                abs(float(self.control._previous_direction[4]))
                < SMOOTHING_ZERO_TOLERANCE
            ),
            "Configured smoothing did not settle within the target-test deadline",
        )
        last = self.control.commands[-1][1].sequence
        await self.wait(
            lambda: self.control.attitude.get("last_control_sequence", 0) >= last,
            "No telemetry confirmation of the final integrated command",
        )
        consumed = self.control.attitude["last_control_sequence"]
        yaw_degrees = sum(
            struct.unpack("<9fI", frame.payload)[4]
            * struct.unpack("<9fI", frame.payload)[8]
            * self.state.rov_config.regulator.yaw.rate
            for _, frame in self.control.commands[start:]
            if frame.sequence <= consumed
        )
        actual = float(
            (
                before.inv() * Rotation.from_quat(self.control.desired_quaternion)
            ).magnitude()
        )
        self.report["targets"] = {
            "absolute_xyzw": target.as_quat().tolist(),
            "readback_xyzw": list(self.control.desired_quaternion),
            "integrated_expected_rad": math.radians(abs(yaw_degrees)),
            "integrated_readback_rad": actual,
            "last_consumed_sequence": consumed,
        }
        require(actual > ANGLE_TOLERANCE, "No measurable desired-attitude integration")
        require(
            abs(actual - math.radians(abs(yaw_degrees))) < ANGLE_TOLERANCE,
            "Target integration differs from actual source-dt command history",
        )

    def config_response(self, mutation: str) -> tuple[float, Config, bool] | None:
        """Find the canonical response for exactly this mutation."""
        for received, message, persisted in self.messages:
            if isinstance(message, Config) and message.payload.mutation_id == mutation:
                return received, message, persisted
        return None

    def successful_toasts(self, since: float) -> list[float]:
        """Observe real config success messages, not a replaced toast function."""
        return [
            stamp
            for stamp, message, _ in self.messages
            if stamp >= since
            and isinstance(message, ShowToast)
            and message.payload.content.message_key
            == "toasts_rov_config_set_successfully"
        ]

    async def settings(self) -> None:
        """Check APPLIED -> disk -> canonical -> ConfirmConfig -> success, then rejection."""
        regulator = self.state.rov_config.regulator.model_copy(deep=True)
        regulator.fpv_mode = not regulator.fpv_mode
        start = time.monotonic()
        await handle_set_config(
            self.state, PartialRovConfig(regulator=regulator), "hil-apply"
        )
        await self.wait(
            lambda: self.config_response("hil-apply") is not None,
            "Missing canonical config response",
        )
        response = self.config_response("hil-apply")
        if response is None:
            msg = "Missing config response"
            raise AcceptanceError(msg)
        stamp, canonical, persisted = response
        require(
            canonical.payload.error is None and persisted,
            "Configuration not applied/persisted at canonical response",
        )
        commits = [
            (when, frame)
            for when, frame in self.control.acks
            if when >= start
            and frame.payload[0] in (wire.COMMIT, wire.QUERY)
            and frame.payload[1] == wire.APPLIED
            and struct.unpack_from("<II", frame.payload, 4)
            == (self.control._settings_generation, self.control._settings_crc)
        ]
        require(
            bool(commits) and commits[-1][0] <= stamp,
            "No matching actual COMMIT/QUERY APPLIED before canonical config",
        )
        require(
            not self.successful_toasts(start), "Success toast preceded ConfirmConfig"
        )
        confirmation = time.monotonic()
        handle_confirm_config(self.state, "hil-apply")
        await self.wait(
            lambda: bool(self.successful_toasts(start)),
            "No success toast after confirmed applied config",
        )
        power = self.state.rov_config.power.model_copy(deep=True)
        power.thrusters_limit = 101
        previous = self.staged.read_bytes()
        await handle_set_config(self.state, PartialRovConfig(power=power), "hil-reject")
        await self.wait(
            lambda: self.config_response("hil-reject") is not None,
            "Missing rejected mutation response",
        )
        rejected = self.config_response("hil-reject")
        if rejected is None or not rejected[1].payload.error:
            msg = "Invalid settings were not rejected"
            raise AcceptanceError(msg)
        require(
            previous == self.staged.read_bytes(),
            "Rejected settings changed the staged persistent config",
        )
        self.report["settings"] = {
            "applied_ack_at": commits[-1][0],
            "applied_proof_request_type": commits[-1][1].payload[0],
            "canonical_at": stamp,
            "persisted_at_canonical": persisted,
            "confirm_at": confirmation,
            "success_at": self.successful_toasts(start)[0],
            "rejection": "host finite/range validation before MCU commit",
            "rejection_error": rejected[1].payload.error,
        }

    async def leases(self) -> None:
        """Prove stale app input and paused CONTROL stop output while USB RX remains live."""
        self.pilot_active = False
        before = self.control.received[wire.ATTITUDE]
        await asyncio.sleep(LEASE_WAIT)
        require(
            self.control.received[wire.ATTITUDE] > before,
            "No fresh telemetry during app-input expiry",
        )
        require(
            self.control.attitude.get("motors") == [1000] * 8,
            "Stale app input did not yield neutral motor readback",
        )
        flags = struct.unpack("<9fI", self.control.commands[-1][1].payload)[-1]
        require(not flags & 4, "Stale app input was sent as valid")
        app_expiry = dict(self.control.attitude)
        self.pilot_active = True
        await asyncio.sleep(0.1)
        async with self.control._gate:
            before = self.control.received[wire.ATTITUDE]
            await asyncio.sleep(LEASE_WAIT)
            require(
                self.control.received[wire.ATTITUDE] > before,
                "USB reader stopped during the CONTROL pause",
            )
            require(
                self.control.attitude.get("motors") == [1000] * 8,
                "Host lease did not neutralize with live USB RX",
            )
            host_expiry = dict(self.control.attitude)
        self.report["leases"] = {
            "app_expiry": app_expiry,
            "control_pause_s": LEASE_WAIT,
            "host_expiry": host_expiry,
        }

    async def calibration_and_maintenance(self) -> None:
        """Use the real cancel handler and sticky maintenance gate; never upload ESC code."""
        await handle_set_auto_stabilization(self.state, False)
        await self.wait(
            lambda: self.control.attitude.get("motors") == [1000] * 8,
            "Not neutral before calibration",
        )
        await handle_start_thruster_test(self.state, 0)
        await self.wait(
            lambda: self.control.attitude.get("motors") == [1100] + [1000] * 7,
            "No hardware-channel calibration readback",
        )
        calibration = dict(self.control.attitude)
        await handle_cancel_thruster_test(self.state, 0)
        await self.wait(
            lambda: self.control.attitude.get("motors") == [1000] * 8,
            "Calibration cancel did not neutralize",
        )
        old_session = self.control.session
        await self.control.enter_maintenance()
        require(
            self.control._maintenance and self.control.session == 0,
            "Maintenance authority was not latched",
        )
        commands = len(self.control.commands)
        await asyncio.sleep(LEASE_WAIT)
        require(
            len(self.control.commands) == commands,
            "CONTROL leaked while maintenance was latched",
        )
        latch_writes = len(self.control.commands) - commands
        self.control.leave_maintenance()
        await self.ready()
        require(
            self.control.session != old_session,
            "Maintenance reused the previous session",
        )
        await self.wait(
            lambda: self.control.attitude.get("last_control_sequence", 0) > 0,
            "No fresh CONTROL after maintenance resynchronization",
        )
        self.report["calibration_maintenance"] = {
            "calibration": calibration,
            "cancelled": True,
            "old_session": old_session,
            "new_session": self.control.session,
            "control_writes_during_latch": latch_writes,
            "esc_upload": "not attempted",
        }

    async def cleanup(self) -> None:
        """Restore the staged baseline and neutralize before the serial transport closes."""
        self.pilot_active = False
        self.pilot.fill(0)
        self.state.thrusters.test_thruster = None
        self.state.thrusters.last_direction_time = 0
        self.state.system_status.auto_stabilization = False
        self.state.system_status.depth_hold = False
        if self.control._maintenance:
            self.control.leave_maintenance()
        if self.control._negotiated:
            await self.control.apply_config(self.baseline)
            self.baseline.save()
            self.state.rov_config = self.baseline
            self.control.confirm_persisted_config()
            self.report["restoration"] = {
                "verified": True,
                "generation": self.control._settings_generation,
                "settings_crc32c": self.control._settings_crc,
                "expected_crc32c": wire.crc32c(wire.settings_image(self.baseline)),
            }
        else:
            self.report["restoration"] = {
                "verified": False,
                "reason": "No negotiated session for baseline restore; remain neutral and investigate",
            }
        await self.control.neutral()


def stage_config(args: argparse.Namespace) -> tuple[RovState, RovConfig, bytes]:
    """Copy configuration into a new directory; primary config and recovery state stay read-only."""
    original = args.config.read_bytes()
    args.staging_dir.mkdir(parents=True, exist_ok=False)
    staged = args.staging_dir / "config.json"
    staged.write_bytes(original)
    primary_recovery = esc_recovery._RECOVERY_JOURNAL_PATH
    if primary_recovery.exists():
        require(
            False,
            "Existing ESC recovery journal: perform coordinator-owned recovery before acceptance",
        )
    esc_recovery._RECOVERY_JOURNAL_PATH = args.staging_dir / "esc-recovery.json"
    RovConfig._config_path = staged
    state = RovState()
    baseline = state.rov_config.model_copy(deep=True)
    baseline.save()
    return state, baseline, original


async def neutral_and_shutdown(
    control: PicoControl, serial: SerialManager, report: dict[str, Any]
) -> None:
    """Record cleanup failures explicitly rather than hiding them behind a passing run."""
    try:
        async with asyncio.timeout(1):
            await control.neutral()
        report["final_neutral_sent"] = True
    except Exception as error:
        report["final_neutral_error"] = str(error)
    try:
        async with asyncio.timeout(2):
            await serial.shutdown()
        report["serial_shutdown"] = True
    except Exception as error:
        report["serial_shutdown_error"] = str(error)


async def run(args: argparse.Namespace, report: dict[str, Any]) -> None:
    """Execute bounded scenarios and always attempt restoration/neutral/USB shutdown."""
    state, baseline, original = stage_config(args)
    serial = NoFlashSerial(state, str(args.port))
    control = ObservedControl(state, serial, args.expected_build_identity)
    state.pico = control
    mcu = NoFlashMcu(state, serial)
    pressure = PressureSensor(state)
    harness = Harness(
        state,
        control,
        args.staging_dir / "config.json",
        baseline,
        args.expected_build_identity,
        args.duration,
        report,
    )
    tasks: list[asyncio.Task[None]] = []
    websocket_state.is_client_connected = (
        True  # Real message/ConfirmConfig contract, no network client needed.
    )
    try:
        async with asyncio.timeout(args.deadline):
            require(
                await serial.initialize(),
                "Could not open the explicitly selected Pico USB port",
            )
            control._reset_connection()  # Keep emergency neutral available even if pressure init fails.
            await pressure.initialize()
            require(
                state.system_health.pressure_sensor_healthy,
                "Real pressure sensor initialization failed",
            )
            # Reuse the exact production acquisition/derivative loop. It has no stop API.
            threading.Thread(
                target=pressure._blocking_read_loop,
                daemon=True,
                name="acceptance-pressure",
            ).start()
            tasks = [
                asyncio.create_task(mcu.read_loop()),
                asyncio.create_task(control.send_loop()),
                asyncio.create_task(harness.pilot_loop()),
                asyncio.create_task(harness.observations()),
            ]
            await harness.ready()
            await harness.cadence()
            await harness.targets()
            await harness.settings()
            await harness.leases()
            await harness.calibration_and_maintenance()
            for task in tasks:
                require(
                    not task.done(), f"Background task stopped unexpectedly: {task}"
                )
    finally:
        try:
            async with asyncio.timeout(12):
                await harness.cleanup()
        except Exception as error:
            report["restoration"] = {"verified": False, "error": str(error)}
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for task in state.config_confirmation_tasks:
                task.cancel()
            await asyncio.gather(
                *state.config_confirmation_tasks, return_exceptions=True
            )
            await neutral_and_shutdown(control, serial, report)
            websocket_state.is_client_connected = False
            baseline.save()  # Staged path only, even if hardware restore was unavailable.
            report["primary_config_unchanged"] = args.config.read_bytes() == original
            report["staged_config"] = str(harness.staged)


def arguments() -> argparse.Namespace:
    """Parse explicit opt-in and portable staging inputs without accessing hardware."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--service-stopped",
        action="store_true",
        help="Confirm the original firmware service is stopped",
    )
    parser.add_argument(
        "--escs-disconnected",
        action="store_true",
        help="Required: scenarios can issue nonzero motor commands",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Read-only known baseline configuration",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        required=True,
        help="New, nonexistent directory for test-only persistent files",
    )
    parser.add_argument(
        "--port",
        type=Path,
        required=True,
        help="Explicit Pico device path, preferably /dev/serial/by-id/...",
    )
    parser.add_argument(
        "--expected-build-identity",
        required=True,
        help="Exact pico-control-dev:... identity expected from this image",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=12,
        help="Active measurement seconds, minimum 12 for full 5 s device windows",
    )
    parser.add_argument(
        "--deadline",
        type=float,
        default=120,
        help="Total scenario deadline; cleanup adds at most 15 s",
    )
    args = parser.parse_args()
    require(
        args.execute and args.service_stopped and args.escs_disconnected,
        "Require --execute --service-stopped --escs-disconnected",
    )
    require(
        os.environ.get("MANAFISH_PICO_CONTROL_DEVELOPMENT") == "1",
        "Require MANAFISH_PICO_CONTROL_DEVELOPMENT=1",
    )
    require(
        args.expected_build_identity.startswith("pico-control-dev:"),
        "Require an explicit development build identity",
    )
    require(
        DURATION_RANGE[0] <= args.duration <= DURATION_RANGE[1]
        and DEADLINE_RANGE[0] <= args.deadline <= DEADLINE_RANGE[1],
        "Duration must be 12..30 s and deadline 60..300 s",
    )
    args.config = args.config.resolve(strict=True)
    args.staging_dir = args.staging_dir.resolve()
    args.port = args.port.resolve(strict=True)
    return args


def main() -> None:
    """Emit one JSON summary and exit nonzero for failures or unverified restoration."""
    report: dict[str, Any] = {
        "test": "pico-python-stack-acceptance",
        "passed": False,
        "automatic_reflash": "disabled in both real-stack installer hooks",
        "clock": "local monotonic only; no cross-machine wall-clock comparisons",
        "unsupported": [
            "powered motors/ESC reception or programming",
            "forced hardware starvation/CRC fault injection",
            "network WebSocket/Tauri rendering",
            "IMU or pressure unplug fault injection",
            "p99 execution timing (not in STATS v1)",
        ],
    }
    loop: asyncio.AbstractEventLoop | None = None
    try:
        args = arguments()
        report["baseline_sha256"] = hashlib.sha256(args.config.read_bytes()).hexdigest()
        report["port"] = str(args.port)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with contextlib.redirect_stdout(sys.stderr):
            loop.run_until_complete(run(args, report))
        report["passed"] = (
            bool(report.get("restoration", {}).get("verified"))
            and report.get("primary_config_unchanged") is True
            and report.get("final_neutral_sent") is True
            and report.get("serial_shutdown") is True
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if loop is not None:
            loop.close()
    sys.stdout.write(json.dumps(report, allow_nan=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    # Production pressure acquisition is intentionally infinite. Bypass interpreter
    # thread-join shutdown only AFTER bounded neutral/restore/serial cleanup and JSON.
    os._exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
