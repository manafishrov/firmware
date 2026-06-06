"""Thruster control logic for the ROV firmware."""

import asyncio
from asyncio import StreamWriter
import struct
import time
from typing import cast

import numpy as np
from numpy.typing import NDArray

from .constants import (
    MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION,
    MCU_CONFIG_START_BYTE,
    MCU_PROTOCOL_DSHOT,
    MCU_PROTOCOL_PWM,
    MOTOR_DEADZONE,
    NUM_MOTORS,
    NV_DECAY_RATE,
    THRUSTER_FORWARD_PULSE_RANGE,
    THRUSTER_INPUT_START_BYTE,
    THRUSTER_NEUTRAL_PULSE_WIDTH,
    THRUSTER_REVERSE_PULSE_RANGE,
    THRUSTER_SEND_FREQUENCY,
    THRUSTER_TEST_DURATION_SECONDS,
    THRUSTER_TEST_TOAST_ID,
    THRUSTER_TIMEOUT_MS,
)
from .log import log_error, log_warn
from .models.toast import ToastVariant
from .regulator import Regulator
from .rov_state import RovState
from .serial import SerialManager
from .toast import ToastContent, cancel_thruster_test_action, toast_content


class Thrusters:
    """Thrusters control class."""

    def __init__(
        self,
        state: RovState,
        serial_manager: SerialManager,
        regulator: Regulator,
    ):
        """Initialize the thrusters.

        Args:
            state: The ROV state.
            serial_manager: The serial manager.
            regulator: The regulator.
        """
        self.state: RovState = state
        self.serial_manager: SerialManager = serial_manager
        self.regulator: Regulator = regulator
        self._last_sent_protocol_config: tuple[str, int] | None = None
        self._last_config_generation: int = -1

        self.previous_direction_vector: NDArray[np.float32] = np.zeros(
            8, dtype=np.float32
        )
        self._direction_vector_buffer: NDArray[np.float32] = np.zeros(
            8, dtype=np.float32
        )
        self._smoothing_buffer: NDArray[np.float32] = np.zeros(8, dtype=np.float32)
        self._thrust_vector_buffer: NDArray[np.float32] = np.zeros(
            NUM_MOTORS, dtype=np.float32
        )
        self._work_indicator_thrust_vector: NDArray[np.float32] = np.zeros(
            NUM_MOTORS, dtype=np.float32
        )
        self._test_thrust_vector: NDArray[np.float32] = np.zeros(
            NUM_MOTORS, dtype=np.float32
        )
        self._zero_thrust_vector: NDArray[np.float32] = np.zeros(
            NUM_MOTORS, dtype=np.float32
        )
        self._reorder_buffer: NDArray[np.float32] = np.zeros(
            NUM_MOTORS, dtype=np.float32
        )
        self._previous_nv_activations: list[float] = []
        self._previous_deadzones_under_activations: list[set[int]] = []

    def _smooth_direction_vector(
        self,
        direction_vector: NDArray[np.float32],
        previous_direction_vector: NDArray[np.float32],
    ) -> None:
        smoothing_factor = self.state.rov_config.smoothing_factor

        if smoothing_factor <= 1 / THRUSTER_SEND_FREQUENCY:
            return

        direction_vector_step = 1 / (THRUSTER_SEND_FREQUENCY * smoothing_factor)

        np.subtract(
            direction_vector, previous_direction_vector, out=self._smoothing_buffer
        )
        _ = np.clip(
            self._smoothing_buffer,
            -direction_vector_step,
            direction_vector_step,
            out=self._smoothing_buffer,
            dtype=np.float32,
        )
        np.add(previous_direction_vector, self._smoothing_buffer, out=direction_vector)

    def _create_thrust_vector_from_direction_vector(
        self,
        direction_vector: NDArray[np.float32],
        out: NDArray[np.float32] | None = None,
    ) -> NDArray[np.float32]:
        allocation_matrix = cast(
            NDArray[np.float32], self.state.rov_config.thruster_allocation
        )
        if out is None:
            return cast(NDArray[np.float32], allocation_matrix @ direction_vector)
        np.matmul(allocation_matrix, direction_vector, out=out)
        return out

    def _calculate_no_deadzone_intervals(
        self,
        active_nv_indices: NDArray[np.intp],
        active_nv: NDArray[np.float32],
        active_thrust_vector: NDArray[np.float32],
    ) -> tuple[list[tuple[float, float]], NDArray[np.float32]]:
        # Make array with start and stop for the deadzone of each thruster
        # shape: (n_active, 2) — each row is [lower_bound, upper_bound] in thrust space
        thruster_deadzones = np.stack(
            [
                active_thrust_vector - MOTOR_DEADZONE,
                active_thrust_vector + MOTOR_DEADZONE,
            ],
            axis=1,
        )

        # Use the nullspace vector to transform the thruster_deadzones into a new set of deadzones in the nullspace vector space
        # divide each element in thruster_deadzones by the corresponding field in active_nv and flip the sign
        nullspace_deadzones = -(thruster_deadzones / active_nv[:, np.newaxis])
        # sort each nullspace_deadzone so first element in tuple is the smallest
        nullspace_deadzones = np.sort(
            nullspace_deadzones, axis=1
        )  # shape: (n_active, 2)

        # Find available intervals
        # Build list of forbidden intervals by clipping each nullspace_deadzone to the allowed activation range
        forbidden_intervals: list[tuple[float, float]] = []
        for i in range(len(active_nv_indices)):
            lower_bound = max(
                float(nullspace_deadzones[i, 0]),
                -MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION,
            )
            upper_bound = min(
                float(nullspace_deadzones[i, 1]),
                MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION,
            )
            if lower_bound < upper_bound:
                forbidden_intervals.append((lower_bound, upper_bound))
        forbidden_intervals.sort()

        # Merge overlapping forbidden intervals so gaps between them are clean
        merged_forbidden_intervals: list[list[float]] = []
        for lower_bound, upper_bound in forbidden_intervals:
            if (
                merged_forbidden_intervals
                and lower_bound <= merged_forbidden_intervals[-1][1]
            ):
                merged_forbidden_intervals[-1][1] = max(
                    merged_forbidden_intervals[-1][1], upper_bound
                )
            else:
                merged_forbidden_intervals.append([lower_bound, upper_bound])

        # Find the gaps between merged forbidden intervals — these are the available_intervals
        available_intervals: list[tuple[float, float]] = []
        cursor = -MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION
        for lower_bound, upper_bound in merged_forbidden_intervals:
            if cursor < lower_bound:
                available_intervals.append((cursor, lower_bound))
            cursor = max(cursor, upper_bound)
        if cursor < MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION:
            available_intervals.append(
                (cursor, MAX_ALLOWED_NULLSPACE_VECTOR_ACTIVATION)
            )

        return available_intervals, nullspace_deadzones

    def _choose_interval(
        self,
        available_intervals: list[tuple[float, float]],
        nullspace_deadzones: NDArray[np.float32],
        active_nv_indices: NDArray[np.intp],
        previous_deadzones_under_activation: set[int],
        previous_nv_activation: float,
    ) -> tuple[tuple[float, float], set[int]]:
        # Check what available interval requires the least amount of deadzone crossing
        # deadzone i is considered "under" a value when its upper bound is at or below that value
        n_active = len(active_nv_indices)
        interval_crossing_scores: list[
            tuple[tuple[float, float], set[int], int]
        ] = []
        for available_interval in available_intervals:
            midpoint = (available_interval[0] + available_interval[1]) / 2.0
            # make a list deadzones_under_activation of indices of deadzones under the midpoint of the available interval
            deadzones_under_activation = {
                i
                for i in range(n_active)
                if float(nullspace_deadzones[i, 1]) <= midpoint
            }
            # calculate deadzone crossing as the symmetric difference: both entering and exiting a deadzone count
            deadzone_crossing = len(
                deadzones_under_activation.symmetric_difference(
                    previous_deadzones_under_activation
                )
            )
            interval_crossing_scores.append(
                (available_interval, deadzones_under_activation, deadzone_crossing)
            )

        # find the minimum possible deadzone crossing, remove all intervals that have more than the minimum amount of deadzone crossings
        minimum_deadzone_crossings = min(
            crossing for _, _, crossing in interval_crossing_scores
        )
        available_intervals_with_minimum_crossings = [
            (interval, deadzones_under_activation)
            for interval, deadzones_under_activation, crossing in interval_crossing_scores
            if crossing == minimum_deadzone_crossings
        ]

        # If there are multiple intervals left, choose the closest one to the previous_nv_activation
        if len(available_intervals_with_minimum_crossings) > 1:

            def distance_to_closest_point_in_interval(
                interval: tuple[float, float],
                previous_nv_activation: float = previous_nv_activation,
            ) -> float:
                lower_bound, upper_bound = interval
                if lower_bound <= previous_nv_activation <= upper_bound:
                    return 0.0
                return float(
                    min(
                        abs(previous_nv_activation - lower_bound),
                        abs(previous_nv_activation - upper_bound),
                    )
                )

            minimum_distance_to_previous_activation = min(
                distance_to_closest_point_in_interval(interval)
                for interval, _ in available_intervals_with_minimum_crossings
            )
            available_intervals_with_minimum_crossings = [
                (interval, deadzones_under_activation)
                for interval, deadzones_under_activation in available_intervals_with_minimum_crossings
                if distance_to_closest_point_in_interval(interval)
                == minimum_distance_to_previous_activation
            ]

        chosen_interval, chosen_deadzones_under_activation = (
            available_intervals_with_minimum_crossings[0]
        )
        return chosen_interval, chosen_deadzones_under_activation

    def _jump_to_interval_or_decay(
        self,
        chosen_interval: tuple[float, float],
        previous_nv_activation: float,
    ) -> float:
        interval_lower_bound, interval_upper_bound = chosen_interval

        # Move nv_activation to closest point in available interval, decay if available interval contains previous_nv_activation
        if interval_lower_bound <= previous_nv_activation <= interval_upper_bound:
            nv_activation = previous_nv_activation
            # move nv_activation towards 0 by NV_DECAY_RATE
            if nv_activation > 0.0:
                nv_activation = max(nv_activation - NV_DECAY_RATE, 0.0)
            elif nv_activation < 0.0:
                nv_activation = min(nv_activation + NV_DECAY_RATE, 0.0)
            # check that this did not bring it outside the available interval, if it did, set it to the closest point in the available interval
            nv_activation = float(
                np.clip(nv_activation, interval_lower_bound, interval_upper_bound)
            )
        else:
            # set nv_activation to the closest point in the available interval
            nv_activation = float(
                np.clip(
                    previous_nv_activation,
                    interval_lower_bound,
                    interval_upper_bound,
                )
            )
        return nv_activation

    def _remove_deadzone_using_nullspace(  
        self,
        thrust_vector: NDArray[np.float32],
    ) -> None:
        # Return if auto-stabilization is disabled
        if not self.state.system_status.auto_stabilization:
            return

        nullspace_vectors = self.state.rov_config.nullspace_vectors

        if len(nullspace_vectors) == 0:
            return

        # previous_nv_activation and previous_deadzones_under_activation are saved
        # for each nullspace vector between iterations. Resize when config changes.
        if len(self._previous_nv_activations) != len(nullspace_vectors):
            self._previous_nv_activations = [0.0] * len(nullspace_vectors)
            self._previous_deadzones_under_activations = [
                set() for _ in nullspace_vectors
            ]

        for nv_index, nv in enumerate(nullspace_vectors):
            previous_nv_activation = self._previous_nv_activations[nv_index]
            previous_deadzones_under_activation = (
                self._previous_deadzones_under_activations[nv_index]
            )

            # Active indicies are the indicies that contain non-zero values in the nullspace vector
            active_nv_indices = np.nonzero(nv)[0]
            if len(active_nv_indices) == 0:
                continue
            active_nv = nv[active_nv_indices]
            active_thrust_vector = thrust_vector[active_nv_indices]

            available_intervals, nullspace_deadzones = (
                self._calculate_no_deadzone_intervals(
                    active_nv_indices, active_nv, active_thrust_vector
                )
            )

            if not available_intervals:
                nv_activation = 0.0
                # send a warning toast message and move to next nullspace vector
                log_warn(
                    f"No available nullspace activation intervals for nullspace vector {nv_index}"
                )
                self._previous_nv_activations[nv_index] = nv_activation
                self._previous_deadzones_under_activations[nv_index] = set()
                continue

            chosen_interval, chosen_deadzones_under_activation = self._choose_interval(
                available_intervals,
                nullspace_deadzones,
                active_nv_indices,
                previous_deadzones_under_activation,
                previous_nv_activation,
            )

            nv_activation = self._jump_to_interval_or_decay(
                chosen_interval, previous_nv_activation
            )

            # Apply nullspace vector with nv_activation to the thrust vector
            # thrust_vector is modified in-place so subsequent nullspace vectors see the updated values
            thrust_vector[:] += nv * nv_activation

            self._previous_nv_activations[nv_index] = nv_activation
            self._previous_deadzones_under_activations[nv_index] = (
                chosen_deadzones_under_activation
            )

    def _correct_thrust_vector_spin_directions(
        self, thrust_vector: NDArray[np.float32]
    ) -> None:
        spin_directions = cast(
            NDArray[np.int8],
            self.state.rov_config.thruster_pin_setup.spin_directions,
        )
        thrust_vector *= spin_directions

    def _reorder_thrust_vector(self, thrust_vector: NDArray[np.float32]) -> None:
        identifiers = cast(
            NDArray[np.int8], self.state.rov_config.thruster_pin_setup.identifiers
        )
        np.take(thrust_vector, identifiers, out=self._reorder_buffer)
        thrust_vector[:] = self._reorder_buffer

    def _clip_thrust_vector(self, thrust_vector: NDArray[np.float32]) -> None:
        _ = np.clip(thrust_vector, -1.0, 1.0, out=thrust_vector, dtype=np.float32)

    def _calculate_work_indicator_percentage_from_thrust_vector(
        self, thrust_vector: NDArray[np.float32]
    ) -> int:
        total_thrust = 0.0
        for thrust in thrust_vector:
            total_thrust += abs(max(-1.0, min(1.0, float(thrust))))
        work_indicator_percentage = min(100, max(0, (total_thrust / NUM_MOTORS) * 100))
        return int(work_indicator_percentage)

    def _calculate_work_indicator_percentage_from_direction_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> int:
        thrust_vector = self._create_thrust_vector_from_direction_vector(
            direction_vector, self._work_indicator_thrust_vector
        )
        return self._calculate_work_indicator_percentage_from_thrust_vector(
            thrust_vector
        )

    def _create_thrust_vector(self) -> NDArray[np.float32]:
        """Create the final thrust vector for the MCU from the current thruster direction vector.

        The returned vector is produced by smoothing the stored direction vector, applying the regulator to adjust control signals, converting the direction vector into motor thrusts, then reordering, applying per-motor spin-direction multipliers, and clipping each component to the allowed range.

        Returns:
            thrust_vector (ndarray[float32]): 1D array of motor thrust values in the range [-1.0, 1.0], ordered for hardware output and sized to the configured number of motors.
        """
        direction_vector = self._direction_vector_buffer
        direction_vector[:] = cast(
            NDArray[np.float32], self.state.thrusters.direction_vector
        )

        self._smooth_direction_vector(direction_vector, self.previous_direction_vector)
        self.previous_direction_vector[:] = direction_vector

        work_indicator_direction_vector = (
            self.regulator.apply_regulator_to_direction_vector(direction_vector)
        )
        self.state.thrusters.work_indicator_percentage = (
            self._calculate_work_indicator_percentage_from_direction_vector(
                work_indicator_direction_vector
            )
        )

        thrust_vector = self._create_thrust_vector_from_direction_vector(
            direction_vector, self._thrust_vector_buffer
        )

        self._remove_deadzone_using_nullspace(thrust_vector)

        self._reorder_thrust_vector(thrust_vector)
        self._correct_thrust_vector_spin_directions(thrust_vector)
        self._clip_thrust_vector(thrust_vector)

        return thrust_vector

    def _compute_thrust_values(self, thrust_vector: NDArray[np.float32]) -> list[int]:
        thrust_values = cast(
            list[int],
            np.where(
                thrust_vector >= 0,
                THRUSTER_NEUTRAL_PULSE_WIDTH
                + thrust_vector * THRUSTER_FORWARD_PULSE_RANGE,
                THRUSTER_NEUTRAL_PULSE_WIDTH
                + thrust_vector * THRUSTER_REVERSE_PULSE_RANGE,
            )
            .astype(int)
            .tolist(),
        )
        thrust_values = (thrust_values + [THRUSTER_NEUTRAL_PULSE_WIDTH] * NUM_MOTORS)[
            :NUM_MOTORS
        ]
        return thrust_values

    def _handle_thruster_test(
        self, current_time: float, test_thruster: int
    ) -> NDArray[np.float32] | None:
        elapsed = current_time - self.state.thrusters.test_start_time
        if elapsed >= THRUSTER_TEST_DURATION_SECONDS:
            self.state.thrusters.test_thruster = None
            toast_content(
                identifier=THRUSTER_TEST_TOAST_ID,
                variant=ToastVariant.SUCCESS,
                content=ToastContent(
                    message_key="toasts_thruster_test_completed",
                ),
                action=None,
            )
            return None
        else:
            thrust_vector = self._test_thrust_vector
            thrust_vector.fill(0.0)
            thrust_vector[test_thruster] = 0.1
            remaining = int(THRUSTER_TEST_DURATION_SECONDS - elapsed)
            if remaining != self.state.thrusters.last_remaining:
                self.state.thrusters.last_remaining = remaining
                toast_content(
                    identifier=THRUSTER_TEST_TOAST_ID,
                    variant=ToastVariant.LOADING,
                    content=ToastContent(
                        message_key="toasts_thruster_test_title",
                        message_args={"thruster": test_thruster},
                        description_key="toasts_seconds_remaining",
                        description_args={"seconds": remaining},
                    ),
                    action=cancel_thruster_test_action(test_thruster),
                )
            return thrust_vector

    async def _send_packet(
        self, writer: StreamWriter, thrust_values: list[int]
    ) -> None:
        data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
        packet = bytearray([THRUSTER_INPUT_START_BYTE]) + data_payload
        checksum = 0
        for b in packet:
            checksum ^= b
        packet.append(checksum)
        writer.write(packet)
        await writer.drain()

    async def _send_config_packet(self, writer: StreamWriter) -> None:
        protocol = (
            MCU_PROTOCOL_DSHOT
            if self.state.rov_config.thruster_protocol == "dshot"
            else MCU_PROTOCOL_PWM
        )
        dshot_speed = self.state.rov_config.dshot_speed
        packet = bytearray([MCU_CONFIG_START_BYTE, protocol]) + bytearray(
            struct.pack("<H", dshot_speed)
        )
        checksum = 0
        for b in packet:
            checksum ^= b
        packet.append(checksum)
        writer.write(packet)
        await writer.drain()

    async def _ensure_config_sent(self, writer: StreamWriter) -> None:
        current = (
            self.state.rov_config.thruster_protocol,
            self.state.rov_config.dshot_speed,
        )
        generation = self.serial_manager.connection_generation
        if (
            current == self._last_sent_protocol_config
            and generation == self._last_config_generation
        ):
            return
        await self._send_config_packet(writer)
        self._last_sent_protocol_config = current
        self._last_config_generation = generation

    def _determine_thrust_vector(
        self, current_time: float, last_send_time: float
    ) -> tuple[NDArray[np.float32] | None, float]:
        if self.state.regulator.auto_tuning_active:
            tuning_vector = self.regulator.handle_auto_tuning(current_time)
            if tuning_vector is not None:
                direction_vector = tuning_vector
                thrust_vector = self._create_thrust_vector_from_direction_vector(
                    direction_vector
                )
                self._correct_thrust_vector_spin_directions(thrust_vector)
                self._reorder_thrust_vector(thrust_vector)
                self._clip_thrust_vector(thrust_vector)
                self.state.thrusters.work_indicator_percentage = 0
                return thrust_vector, last_send_time

        if self.state.thrusters.test_thruster is not None:
            test_vector = self._handle_thruster_test(
                current_time, self.state.thrusters.test_thruster
            )
            if test_vector is not None:
                self.state.thrusters.work_indicator_percentage = 0
                return test_vector, last_send_time

        if (
            self.state.thrusters.last_direction_time > 0
            and current_time - self.state.thrusters.last_direction_time
            < THRUSTER_TIMEOUT_MS / 1000
        ):
            return self._create_thrust_vector(), current_time

        if current_time - last_send_time > THRUSTER_TIMEOUT_MS / 1000:
            self.state.thrusters.work_indicator_percentage = 0
            return self._zero_thrust_vector, last_send_time

        return None, last_send_time

    async def _send_with_retries(
        self, writer: StreamWriter, thrust_values: list[int]
    ) -> bool:
        for attempt in range(3):
            try:
                await self._send_packet(writer, thrust_values)
                return True
            except Exception as e:
                log_error(f"Thruster send_packet failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(0.1)
        return False

    async def send_loop(self) -> None:
        """Send thruster commands in a continuous loop."""
        thrust_vector = np.zeros(NUM_MOTORS, dtype=np.float32)
        last_send_time = time.time()
        interval = 1.0 / THRUSTER_SEND_FREQUENCY
        next_tick = time.perf_counter() + interval
        while True:
            if not await self.serial_manager.ensure_connection():
                await asyncio.sleep(1)
                next_tick = time.perf_counter() + interval
                continue
            writer = self.serial_manager.get_writer()
            await self._ensure_config_sent(writer)

            current_time = time.time()
            self.regulator.update_regulator_data_from_imu()
            new_thrust_vector, updated_last_send_time = self._determine_thrust_vector(
                current_time, last_send_time
            )
            if new_thrust_vector is not None:
                thrust_vector = new_thrust_vector
                last_send_time = updated_last_send_time

            thrust_values = self._compute_thrust_values(thrust_vector)
            success = await self._send_with_retries(writer, thrust_values)
            if not success:
                await self.serial_manager.handle_connection_lost(
                    "Thruster send failed 3 times, disabling MCU"
                )

            sleep_time = next_tick - time.perf_counter()
            await asyncio.sleep(max(0.0, sleep_time))
            next_tick += interval
            now = time.perf_counter()
            if next_tick < now:
                next_tick = now + interval
