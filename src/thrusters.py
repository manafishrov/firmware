"""Thruster control logic for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from numpy.typing import NDArray


if TYPE_CHECKING:
    from .regulator import Regulator
    from .rov_state import RovState
    from .serial import SerialManager

import asyncio
from asyncio import StreamWriter
import struct
import time

import numpy as np

from .constants import (
    NUM_MOTORS,
    THRUSTER_FORWARD_PULSE_RANGE,
    THRUSTER_INPUT_START_BYTE,
    THRUSTER_NEUTRAL_PULSE_WIDTH,
    THRUSTER_REVERSE_PULSE_RANGE,
    THRUSTER_TEST_DURATION_SECONDS,
    THRUSTER_TEST_TOAST_ID,
    THRUSTER_TIMEOUT_MS,
)
from .log import log_error
from .toast import toast_loading, toast_success


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

    def _scale_direction_vector_with_user_max_power(
        self, direction_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        scale = self.state.rov_config.power.user_max_power
        _ = np.multiply(direction_vector, scale, out=direction_vector)
        return direction_vector

    def _create_thrust_vector_from_thruster_allocation(
        self, direction_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        allocation_matrix = cast(
            NDArray[np.float32], self.state.rov_config.thruster_allocation
        )
        direction_vector_np = direction_vector.reshape(-1)
        cols = direction_vector_np.shape[0]
        allocation_matrix = allocation_matrix[:, :cols]
        thrust_vector = allocation_matrix @ direction_vector_np
        return thrust_vector

    def _correct_thrust_vector_spin_directions(
        self, thrust_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        spin_directions = cast(
            NDArray[np.int8],
            self.state.rov_config.thruster_pin_setup.spin_directions,
        )
        thrust_vector = thrust_vector * spin_directions
        _ = np.clip(thrust_vector, -1, 1, out=thrust_vector)
        return thrust_vector

    def _reorder_thrust_vector(
        self, thrust_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        identifiers = cast(
            NDArray[np.int8], self.state.rov_config.thruster_pin_setup.identifiers
        )
        reordered = np.zeros(len(identifiers), dtype=np.float32)
        for i in range(len(identifiers)):
            reordered[i] = thrust_vector[identifiers[i]]
        return reordered

    def _prepare_thrust_vector(
        self, direction_vector: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        self.regulator.update_regulator_data_from_imu()
        self.regulator.update_desired_from_direction_vector(direction_vector)
        direction_vector = self._scale_direction_vector_with_user_max_power(
            direction_vector
        )
        if (
            self.state.system_status.pitch_stabilization
            or self.state.system_status.roll_stabilization
            or self.state.system_status.depth_hold
        ):
            regulator_actuation = self.regulator.get_actuation()
        else:
            regulator_actuation = np.zeros(8, dtype=np.float32)
        direction_vector += regulator_actuation
        thrust_vector = self._create_thrust_vector_from_thruster_allocation(
            direction_vector
        )
        thrust_vector = self._correct_thrust_vector_spin_directions(thrust_vector)
        thrust_vector = self._reorder_thrust_vector(thrust_vector)
        return thrust_vector

    def _compute_thrust_values(self, thrust_vector: NDArray[np.float32]) -> list[int]:
        thrust_values: list[int] = []
        for val in thrust_vector:  # pyright: ignore[reportAny]
            val_typed = cast(np.float32, val)
            if val_typed >= 0:
                thruster_val = int(
                    THRUSTER_NEUTRAL_PULSE_WIDTH
                    + val_typed * THRUSTER_FORWARD_PULSE_RANGE
                )
            else:
                thruster_val = int(
                    THRUSTER_NEUTRAL_PULSE_WIDTH
                    + val_typed * THRUSTER_REVERSE_PULSE_RANGE
                )
            thrust_values.append(thruster_val)
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
            toast_success(
                toast_id=THRUSTER_TEST_TOAST_ID,
                message="Thruster test completed",
                description=None,
                cancel=None,
            )
            return None
        else:
            thrust_vector = np.zeros(NUM_MOTORS, dtype=np.float32)
            logical_index = test_thruster
            identifiers = cast(
                NDArray[np.int8], self.state.rov_config.thruster_pin_setup.identifiers
            )
            hardware_index = (identifiers[logical_index],)
            thrust_vector[hardware_index] = 0.1
            remaining = int(THRUSTER_TEST_DURATION_SECONDS - elapsed)
            if remaining != self.state.thrusters.last_remaining:
                self.state.thrusters.last_remaining = remaining
                toast_loading(
                    toast_id=THRUSTER_TEST_TOAST_ID,
                    message=f"Testing thruster {logical_index}",
                    description=f"{remaining} seconds remaining",
                    cancel=None,
                )
            return thrust_vector

    def _send_packet(self, writer: StreamWriter, thrust_values: list[int]) -> None:
        data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
        packet = bytearray([THRUSTER_INPUT_START_BYTE]) + data_payload
        checksum = 0
        for b in packet:
            checksum ^= b
        packet.append(checksum)
        writer.write(packet)

    def _determine_thrust_vector(
        self, current_time: float, last_send_time: float
    ) -> tuple[NDArray[np.float32] | None, float]:
        if self.state.regulator.auto_tuning_active:
            tuning_vector = self.regulator.handle_auto_tuning(current_time)
            if tuning_vector is not None:
                direction_vector = tuning_vector
                thrust_vector = self._create_thrust_vector_from_thruster_allocation(
                    direction_vector
                )
                thrust_vector = self._correct_thrust_vector_spin_directions(
                    thrust_vector
                )
                thrust_vector = self._reorder_thrust_vector(thrust_vector)
                return thrust_vector, last_send_time

        if self.state.thrusters.test_thruster is not None:
            test_vector = self._handle_thruster_test(
                current_time, self.state.thrusters.test_thruster
            )
            if test_vector is not None:
                return test_vector, last_send_time

        if (
            self.state.thrusters.last_direction_time > 0
            and current_time - self.state.thrusters.last_direction_time
            < THRUSTER_TIMEOUT_MS / 1000
        ):
            direction_vector = cast(
                NDArray[np.float32], self.state.thrusters.direction_vector
            )
            return self._prepare_thrust_vector(direction_vector), current_time

        if current_time - last_send_time > THRUSTER_TIMEOUT_MS / 1000:
            return np.zeros(NUM_MOTORS, dtype=np.float32), last_send_time

        return None, last_send_time

    async def _send_with_retries(
        self, writer: StreamWriter, thrust_values: list[int]
    ) -> bool:
        for attempt in range(3):
            try:
                self._send_packet(writer, thrust_values)
                return True
            except Exception as e:
                log_error(f"Thruster send_packet failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(0.1)
        return False

    async def send_loop(self) -> None:
        """Send thruster commands in a continuous loop at 60Hz."""
        writer = self.serial_manager.get_writer()
        thrust_vector = np.zeros(NUM_MOTORS, dtype=np.float32)
        last_send_time = time.time()
        while True:
            if not self.state.system_health.microcontroller_ok:
                await asyncio.sleep(1)
                continue

            current_time = time.time()
            new_thrust_vector, updated_last_send_time = self._determine_thrust_vector(
                current_time, last_send_time
            )
            if new_thrust_vector is not None:
                thrust_vector = new_thrust_vector
                last_send_time = updated_last_send_time

            thrust_values = self._compute_thrust_values(thrust_vector)
            success = await self._send_with_retries(writer, thrust_values)
            if not success:
                self.state.system_health.microcontroller_ok = False
                log_error("Thruster send failed 3 times, disabling microcontroller")

            await asyncio.sleep(1 / 60)
