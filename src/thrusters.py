"""Thruster control logic for the ROV firmware."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from numpy.typing import NDArray

    from .regulator import Regulator
    from .rov_state import RovState
    from .serial import SerialManager

    from .websocket.server import WebsocketServer

import asyncio
import json
import struct
import time

import numpy as np

from .constants import (
    FORWARD_RANGE,
    INPUT_START_BYTE,
    NEUTRAL,
    NUM_MOTORS,
    REVERSE_RANGE,
    THRUSTER_TEST_TOAST_ID,
    TIMEOUT_MS,
)
from .log import log_error
from .models.config import RegulatorPID
from .toast import toast_loading, toast_success
from .websocket.message import RegulatorSuggestions


class Thrusters:
    """Thrusters control class."""

    def __init__(
        self,
        state: RovState,
        serial_manager: SerialManager,
        regulator: Regulator,
        ws_server: WebsocketServer,
    ):
        """Initialize the thrusters.

        Args:
            state: The ROV state.
            serial_manager: The serial manager.
            regulator: The regulator.
            ws_server: The WebSocket server.
        """
        self.state: RovState = state
        self.serial_manager: SerialManager = serial_manager
        self.regulator: Regulator = regulator
        self.ws_server: WebsocketServer = ws_server

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
            regulator_actuation = np.zeros(6)
        direction_vector += regulator_actuation
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
        self, current_time: float, test_thruster: int
    ) -> NDArray[np.float64] | None:
        elapsed = current_time - self.state.thrusters.test_start_time
        if elapsed >= 10:
            self.state.thrusters.test_thruster = None
            toast_success(
                toast_id=THRUSTER_TEST_TOAST_ID,
                message="Thruster test completed",
                description=None,
                cancel=None,
            )
            return None
        else:
            thrust_vector = np.zeros(NUM_MOTORS)
            logical_index = test_thruster
            hardware_index = self.state.rov_config.thruster_pin_setup.identifiers[
                logical_index
            ]
            thrust_vector[hardware_index] = 0.1
            remaining = int(10 - elapsed)
            if remaining != self.state.thrusters.last_remaining:
                self.state.thrusters.last_remaining = remaining
                toast_loading(
                    toast_id=THRUSTER_TEST_TOAST_ID,
                    message=f"Testing thruster {logical_index}",
                    description=f"{remaining} seconds remaining",
                    cancel=None,
                )
            return thrust_vector

    async def _send_packet(self, writer, thrust_values: list[int]) -> None:
        data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
        packet = bytearray([INPUT_START_BYTE]) + data_payload
        checksum = 0
        for b in packet:
            checksum ^= b
        packet.append(checksum)
        await writer.write(packet)

    def _handle_auto_tuning_completion(self) -> None:
        suggestions = RegulatorSuggestions(
            payload={
                "pitch": self.regulator.auto_tuning_params.get(
                    "pitch", RegulatorPID(kp=0, ki=0, kd=0)
                ),
                "roll": self.regulator.auto_tuning_params.get(
                    "roll", RegulatorPID(kp=0, ki=0, kd=0)
                ),
                "depth": self.regulator.auto_tuning_params.get(
                    "depth", RegulatorPID(kp=0, ki=0, kd=0)
                ),
            }
        )
        if self.ws_server.client:
            asyncio.create_task(
                self.ws_server.client.send(
                    json.dumps(suggestions.model_dump(by_alias=True))
                )
            )

    def _determine_thrust_vector(
        self, current_time: float, last_send_time: float
    ) -> tuple[NDArray[np.float64], float]:
        if self.state.regulator.auto_tuning_active:
            tuning_vector, completed = self.regulator.handle_auto_tuning(current_time)
            if completed:
                self._handle_auto_tuning_completion()
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
            < TIMEOUT_MS / 1000
        ):
            direction_vector = self.state.thrusters.direction_vector
            return self._prepare_thrust_vector(direction_vector), current_time

        if current_time - last_send_time > TIMEOUT_MS / 1000:
            return np.zeros(NUM_MOTORS), last_send_time

        return None, last_send_time

    async def _send_with_retries(self, writer, thrust_values: list[int]) -> bool:
        for attempt in range(3):
            try:
                await self._send_packet(writer, thrust_values)
                return True
            except Exception as e:
                log_error(f"Thruster send_packet failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(0.1)
        return False

    async def send_loop(self) -> None:
        writer = self.serial_manager.get_writer()
        thrust_vector = np.zeros(NUM_MOTORS)
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
