from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from rov_state import RovState
    from serial import SerialManager

import asyncio
import time
import struct
import numpy as np
from numpy.typing import NDArray
from toast import toast_loading, toast_success

INPUT_START_BYTE = 0x5A
NUM_MOTORS = 8
NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000
TIMEOUT_MS = 200


class Thrusters:
    def __init__(self, state: RovState, serial_manager: SerialManager):
        self.state: RovState = state
        self.serial_manager: SerialManager = serial_manager

    def _scale_direction_vector_with_user_max_power(
        self, direction_vector: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        scale = self.state.rov_config.power.user_max_power
        np.multiply(direction_vector, scale, out=direction_vector)
        return direction_vector

    def _create_thrust_vector_from_thruster_allocation(
        self, direction_vector: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        allocation_matrix = self.state.rov_config.thruster_allocation
        direction_vector_np = direction_vector.reshape(-1)
        cols = direction_vector_np.shape[0]
        allocation_matrix = allocation_matrix[:, :cols]
        thrust_vector = allocation_matrix @ direction_vector_np
        return thrust_vector

    def _correct_thrust_vector_spin_directions(
        self, thrust_vector: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        spin_directions = self.state.rov_config.thruster_pin_setup.spin_directions
        thrust_vector = thrust_vector * spin_directions
        np.clip(thrust_vector, -1, 1, out=thrust_vector)
        return thrust_vector

    def _reorder_thrust_vector(
        self, thrust_vector: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        identifiers = self.state.rov_config.thruster_pin_setup.identifiers
        reordered = np.zeros(len(identifiers))
        for i in range(len(identifiers)):
            reordered[i] = thrust_vector[identifiers[i]]
        return reordered

    def _prepare_thrust_vector(
        self, direction_vector: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        direction_vector = self._scale_direction_vector_with_user_max_power(
            direction_vector
        )
        thrust_vector = self._create_thrust_vector_from_thruster_allocation(
            direction_vector
        )
        thrust_vector = self._correct_thrust_vector_spin_directions(thrust_vector)
        thrust_vector = self._reorder_thrust_vector(thrust_vector)
        return thrust_vector

    def _compute_thrust_values(self, thrust_vector: NDArray[np.float64]) -> list[int]:
        thrust_values = []
        for val in thrust_vector:
            if val >= 0:
                thruster_val = int(NEUTRAL + val * FORWARD_RANGE)
            else:
                thruster_val = int(NEUTRAL + val * REVERSE_RANGE)
            thrust_values.append(thruster_val)
        thrust_values = (thrust_values + [NEUTRAL] * NUM_MOTORS)[:NUM_MOTORS]
        return thrust_values

    def _handle_thruster_test(
        self, current_time: float
    ) -> Optional[NDArray[np.float64]]:
        if self.state.thrusters.test_thruster is not None:
            elapsed = current_time - self.state.thrusters.test_start_time
            if elapsed >= 10:
                self.state.thrusters.test_thruster = None
                toast_success(
                    id="thruster-test",
                    message="Thruster test completed",
                    description=None,
                    cancel=None,
                )
                return None
            else:
                thrust_vector = np.zeros(NUM_MOTORS)
                logical_index = self.state.thrusters.test_thruster
                hardware_index = self.state.rov_config.thruster_pin_setup.identifiers[
                    logical_index
                ]
                thrust_vector[hardware_index] = 0.1
                remaining = int(10 - elapsed)
                if remaining != self.state.thrusters.last_remaining:
                    self.state.thrusters.last_remaining = remaining
                    toast_loading(
                        id="thruster-test",
                        message=f"Testing thruster {logical_index}",
                        description=f"{remaining} seconds remaining",
                        cancel=None,
                    )
                return thrust_vector
        return None

    async def _send_packet(self, serial, thrust_values: list[int]) -> None:
        data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
        packet = bytearray([INPUT_START_BYTE]) + data_payload
        checksum = 0
        for b in packet:
            checksum ^= b
        packet.append(checksum)
        await serial.write(packet)

    async def send_loop(self) -> None:
        serial = self.serial_manager.get_serial()
        thrust_vector = np.zeros(NUM_MOTORS)
        last_send_time = time.time()
        while True:
            if not self.state.system_health.microcontroller_ok:
                await asyncio.sleep(1)
                continue
            current_time = time.time()
            test_vector = self._handle_thruster_test(current_time)
            if test_vector is not None:
                thrust_vector = test_vector
            elif (
                self.state.thrusters.last_direction_time > 0
                and current_time - self.state.thrusters.last_direction_time
                < TIMEOUT_MS / 1000
            ):
                direction_vector = self.state.thrusters.direction_vector
                thrust_vector = self._prepare_thrust_vector(direction_vector)
                last_send_time = current_time
            elif current_time - last_send_time > TIMEOUT_MS / 1000:
                thrust_vector = np.zeros(NUM_MOTORS)
            thrust_values = self._compute_thrust_values(thrust_vector)
            await self._send_packet(serial, thrust_values)
            await asyncio.sleep(1 / 60)
