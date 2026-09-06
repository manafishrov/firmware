"""Bounded field diagnostics carried by the existing debug log stream.

Sampling and serialization run separately from motor writes. These observations
never change control, current limits, or update/recovery policy.
"""

import asyncio
from collections import deque
import hashlib
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING, cast

from .constants import THRUSTER_TIMEOUT_MS
from .log import log_info, log_warn
from .models.config import CURRENT_FIRMWARE_VERSION
from .sensors.pi_power import read_pi_undervoltage
from .websocket.state import websocket_state


if TYPE_CHECKING:
    from .rov_state import RovState
    from .sensors.mcu import McuSensor
    from .serial import SerialManager
    from .thrusters import Thrusters


_SAMPLE_SECONDS = 1.0
_SUMMARY_SECONDS = 10.0
_HISTORY_SAMPLES = 60
_HISTORY_COOLDOWN_SECONDS = 30.0
_CONFIG_FIELDS = {
    "mcu_board",
    "thruster_protocol",
    "dshot_speed",
    "current_sensing_mode",
    "thruster_pin_setup",
    "thruster_allocation",
    "nullspace_vectors",
    "regulator",
    "direction_coefficients",
    "power",
    "smoothing_factor",
    "camera",
}


def log_diagnostic(event: str, **fields: object) -> None:
    """Emit allowlisted call-site fields, not arbitrary application configuration."""
    log_info(
        "diagnostic " + json.dumps({"event": event, **fields}, separators=(",", ":"))
    )


def firmware_manifest(home: Path) -> list[dict[str, object]]:
    """Hash staged images off the control loop; never inspect keys or credentials."""
    images: list[dict[str, object]] = []
    for directory, pattern in (("mcu-firmware", "*.uf2"), ("esc-firmware", "esc-v*.*")):
        for path in sorted((home / directory).glob(pattern)):
            if path.suffix not in {".uf2", ".bin", ".hex"}:
                continue
            try:
                with path.open("rb") as image:
                    digest = hashlib.file_digest(image, "sha256").hexdigest()
                images.append(
                    {"file": path.name, "sha256": digest, "bytes": path.stat().st_size}
                )
            except OSError:
                images.append({"file": path.name, "error": "unreadable"})
    return images


class FieldDiagnostics:
    """One sample/second, one normal log/ten seconds, bounded fault history."""

    def __init__(
        self,
        state: "RovState",
        serial: "SerialManager",
        mcu: "McuSensor",
        thrusters: "Thrusters",
    ) -> None:
        """Observe the existing state owners without adding control dependencies."""
        self.state = state
        self.serial = serial
        self.mcu = mcu
        self.thrusters = thrusters
        self._history: deque[dict[str, object]] = deque(maxlen=_HISTORY_SAMPLES)
        self._last_summary = float("-inf")
        self._last_history = float("-inf")
        self._last_state: str | None = None
        self._last_config: str | None = None
        self._last_faults: frozenset[str] = frozenset()
        self._connected = False
        self._client_generation = -1
        self._manifest: list[dict[str, object]] = []
        self._system_path: str | None = None
        self._last_invalid_usb_packets = 0
        self._input_was_fresh = False
        self._pending_faults: dict[str, float] = {}
        self._events: list[tuple[str, dict[str, object]]] | None = None

    def _emit(self, event: str, **fields: object) -> None:
        if self._events is None:
            log_diagnostic(event, **fields)
        else:
            self._events.append((event, fields))

    def sample(
        self,
        now: float,
        *,
        undervoltage: bool | None,
        scheduler_lag: float = 0.0,
        power_probe_s: float = 0.0,
    ) -> None:
        """Capture only observed values; an old/missing sample is never a zero."""
        state = self.state
        connected = websocket_state.is_client_connected
        new_connection = connected and (
            not self._connected
            or self._client_generation != websocket_state.connection_generation
        )
        self._connected = connected
        self._client_generation = websocket_state.connection_generation
        config = state.rov_config.model_dump(mode="json", include=_CONFIG_FIELDS)
        config_key = json.dumps(config, sort_keys=True)
        if config_key != self._last_config or new_connection:
            self._emit(
                "configuration",
                firmware=CURRENT_FIRMWARE_VERSION,
                images=self._manifest,
                system_path=self._system_path,
                utc_clock_verified=False,
                telemetry_units={
                    "erpm": "electrical RPM",
                    "voltage": "V",
                    "temperature": "C",
                    "current": "signed wire A",
                    "signal_quality": "%",
                },
                command_units="USB throttle counts 0..2000 (1000 neutral), physical channels 1-8; not electrical pulse widths or ESC acknowledgements",
                config=config,
            )
            self._last_config = config_key
        status = {
            "usb_generation": self.serial.connection_generation,
            "usb_connected": state.system_health.mcu_healthy,
            "protocol_state": state.system_status.thruster_protocol_state,
            "protocol_error": state.system_status.thruster_protocol_error,
            "ready": state.system_status.thruster_control_ready,
            "identity": state.device_info.model_dump(mode="json"),
            "health": state.system_health.model_dump(mode="json"),
            "pico_flashing": state.mcu_flashing,
            "esc_update": state.esc_firmware_update.model_dump(mode="json"),
            "pi_undervoltage": undervoltage,
        }
        # Progress itself is logged by the updater, not once per percentage here.
        state_key = json.dumps(
            {key: value for key, value in status.items() if key != "esc_update"},
            sort_keys=True,
        )
        if state_key != self._last_state or new_connection:
            self._emit("state", **status)
            self._last_state = state_key
        telemetry = self.mcu.diagnostic_snapshot(now)
        last_input = state.thrusters.last_direction_time
        input_age = max(0.0, time.time() - last_input) if last_input > 0 else None
        watchdog_neutral = (
            (input_age is None or input_age >= THRUSTER_TIMEOUT_MS / 1000)
            and state.thrusters.test_thruster is None
            and not state.regulator.auto_tuning_active
        )
        vector = state.thrusters.direction_vector
        snapshot: dict[str, object] = {
            "mono_s": round(now, 3),
            "usb_generation": self.serial.connection_generation,
            "ready": state.system_status.thruster_control_ready,
            "input_age_s": None if input_age is None else round(input_age, 3),
            "input_expired": watchdog_neutral,
            "requested_direction": None if vector is None else vector.tolist(),
            "control": self.thrusters.diagnostic_snapshot(now),
            "regulator": state.regulator.model_dump(
                mode="json",
                include={
                    "pitch",
                    "roll",
                    "yaw",
                    "desired_pitch",
                    "desired_roll",
                    "desired_yaw",
                    "desired_depth",
                },
            ),
            "auto_stabilization": state.system_status.auto_stabilization,
            "depth_hold": state.system_status.depth_hold,
            "depth_m": state.pressure.depth
            if state.system_health.pressure_sensor_healthy
            else None,
            "pi_undervoltage": undervoltage,
            "sampler_lag_s": round(scheduler_lag, 4),
            "power_probe_s": round(power_probe_s, 4),
            "invalid_usb_packets": self.mcu.invalid_usb_packets,
            "esc": telemetry,
        }
        self._history.append(snapshot)
        faults = self._faults(telemetry, undervoltage)
        new_faults = faults - self._last_faults
        if self._input_was_fresh and watchdog_neutral:
            self._emit("input_watchdog_expired", input_age_s=input_age)
            new_faults = new_faults | {"input_watchdog_expired"}
        self._input_was_fresh = not watchdog_neutral
        if self.mcu.invalid_usb_packets > self._last_invalid_usb_packets:
            new_faults = new_faults | {"invalid_usb_packet"}
        self._last_invalid_usb_packets = self.mcu.invalid_usb_packets
        for reason in new_faults:
            self._pending_faults.setdefault(reason, now)
        if (
            self._pending_faults
            and now - self._last_history >= _HISTORY_COOLDOWN_SECONDS
        ):
            self._emit(
                "fault_history",
                reasons=dict(self._pending_faults),
                sample_interval_s=_SAMPLE_SECONDS,
                sample_count=len(self._history),
                history_id=round(now, 3),
            )
            # Separate records avoid journal line truncation and huge viewer rows.
            for sample in self._history:
                self._emit("history_sample", history_id=round(now, 3), **sample)
            self._pending_faults.clear()
            self._last_history = now
        if now - self._last_summary >= _SUMMARY_SECONDS or new_connection:
            self._emit("snapshot", **self._summary(snapshot))
            self._last_summary = now
        self._last_faults = faults

    def _summary(self, snapshot: dict[str, object]) -> dict[str, object]:
        # Extrema span every one-second sample, not just the tenth second.
        window = [
            sample
            for sample in self._history
            if cast(float, sample["mono_s"]) > round(self._last_summary, 3)
        ]
        telemetry = [cast(list[dict[str, object]], sample["esc"]) for sample in window]
        channels = [
            dict(channel) for channel in cast(list[dict[str, object]], snapshot["esc"])
        ]
        for index, channel in enumerate(channels):
            lows = [row[index]["erpm_min_since_sample"] for row in telemetry]
            highs = [row[index]["erpm_max_since_sample"] for row in telemetry]
            channel["erpm_window_min"] = min(
                (value for value in lows if isinstance(value, (int, float))),
                default=None,
            )
            channel["erpm_window_max"] = max(
                (value for value in highs if isinstance(value, (int, float))),
                default=None,
            )
        controls = [cast(dict[str, object], sample["control"]) for sample in window]
        control = dict(cast(dict[str, object], snapshot["control"]))
        control["max_write_gap_s"] = max(
            (cast(float, row["max_write_gap_s"]) for row in controls), default=0.0
        )
        control["write_gaps_over_two_periods"] = sum(
            cast(int, row["write_gaps_over_two_periods"]) for row in controls
        )
        for suffix, operation in (("min", min), ("max", max)):
            values = [
                cast(list[int], row[f"usb_command_{suffix}_since_sample"])
                for row in controls
                if row[f"usb_command_{suffix}_since_sample"] is not None
            ]
            control[f"usb_command_window_{suffix}"] = (
                [operation(channel) for channel in zip(*values, strict=True)]
                if values
                else None
            )
        return {
            **snapshot,
            "esc": channels,
            "control": control,
            "window_start_mono_s": window[0]["mono_s"]
            if window
            else snapshot["mono_s"],
            "window_sample_count": len(window),
        }

    def _faults(
        self, telemetry: list[dict[str, object]], undervoltage: bool | None
    ) -> frozenset[str]:
        faults: set[str] = set()
        if undervoltage:
            faults.add("pi_undervoltage")
        if self.state.system_status.thruster_protocol_state == "failed":
            faults.add("protocol_failed")
        if self._last_state is not None and not self.state.system_health.mcu_healthy:
            faults.add("usb_disconnected")
        if self.state.esc_firmware_update.error:
            faults.add("esc_update_failed")
        for channel in telemetry:
            if channel["erpm_stale"]:
                faults.add(f"erpm_stale_{channel['channel']}")
        return frozenset(faults)

    async def run(self) -> None:
        """Diagnostics failures must not stop the ROV or cause a log storm."""
        try:
            self._manifest = await asyncio.to_thread(firmware_manifest, Path.home())
            try:
                self._system_path = str(Path("/run/current-system").readlink())
            except OSError:
                self._system_path = None
        except Exception as error:
            log_warn(f"Diagnostic firmware inventory failed: {type(error).__name__}")
        next_sample = time.monotonic()
        last_error = float("-inf")
        while True:
            await asyncio.sleep(max(0.0, next_sample - time.monotonic()))
            probe_start = time.monotonic()
            events: list[tuple[str, dict[str, object]]] = []
            self._events = events
            try:
                undervoltage = await asyncio.to_thread(read_pi_undervoltage)
                captured_at = time.monotonic()
                self.sample(
                    captured_at,
                    undervoltage=undervoltage,
                    scheduler_lag=max(0.0, captured_at - next_sample),
                    power_probe_s=captured_at - probe_start,
                )
                # Serialize bounded records one at a time, yielding to motor IO.
                for event, fields in events:
                    log_diagnostic(event, **fields)
                    await asyncio.sleep(0)
            except Exception as error:
                now = time.monotonic()
                if now - last_error >= _HISTORY_COOLDOWN_SECONDS:
                    log_warn(
                        f"Field diagnostics failed: {type(error).__name__}: {error}"
                    )
                    last_error = now
            finally:
                self._events = None
            next_sample += _SAMPLE_SECONDS
            now = time.monotonic()
            if next_sample < now:
                next_sample += (
                    int((now - next_sample) / _SAMPLE_SECONDS) + 1
                ) * _SAMPLE_SECONDS
