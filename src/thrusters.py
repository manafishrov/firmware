from rov_state import ROVState
from log import log_error, log_info
import numpy as np
import serial
import glob
import sys


class Thrusters:
    def __init__(self, state: ROVState):
        self.state: ROVState = state
        self.erpms: list[float] = [0.0] * 8
        self.serial = None

    async def _find_pico_port(self) -> str:
        pico_ports = glob.glob("/dev/serial/by-id/usb-Raspberry_Pi_Pico*")
        if not pico_ports:
            pico_ports = glob.glob("/dev/ttyACM*")
        if pico_ports:
            return pico_ports[0]
        else:
            await log_error("Error: Could not find Raspberry Pi Pico serial port.")
            sys.exit(1)

    async def initialize(self) -> None:
        try:
            serial_port_path = await self._find_pico_port()
            self.serial = serial.Serial(serial_port_path, 115200, timeout=0.01)
        except Exception as e:
            await log_error(f"Error opening serial port: {e}")
            sys.exit(1)

    def _scale_vector_with_user_max_power(self, direction_vector: list[float]) -> None:
        scale = self.state.rov_config["power"]["userMaxPower"]
        np.multiply(direction_vector, scale, out=direction_vector)

    def _create_thrust_vector_from_thruster_allocation(
        self, direction_vector: list[float]
    ) -> list[float]:
        allocation_matrix = np.array(self.state.rov_config["thrusterAllocation"])
        # TODO: Remove this cutoff when actions are sent as part of the direction vector
        allocation_matrix = allocation_matrix[:6, :]
        direction_vector_np = np.array(direction_vector)
        thrust_vector = allocation_matrix @ direction_vector_np
        return thrust_vector.tolist()

    def _correct_spin_direction(self, thrust_vector: list[float]) -> list[float]:
        spin_directions = np.array(
            self.state.rov_config["thrusterPinSetup"]["spinDirections"]
        )
        return thrust_vector * spin_directions

    def _reorder_thrust_vector(self, thrust_vector: list[float]) -> list[float]:
        identifiers = self.state.rov_config["thrusterPinSetup"]["identifiers"]
        reordered = [0.0] * len(identifiers)
        for src_idx, dest_idx in enumerate(identifiers):
            reordered[dest_idx] = thrust_vector[src_idx]
        return reordered

    def run_thrusters_with_regulator(self, direction_vector: list[float]) -> None:
        self._scale_vector_with_user_max_power(direction_vector)
        thrust_vector = self._create_thrust_vector_from_thruster_allocation(
            direction_vector
        )
        self.run_thrusters(thrust_vector)

    def run_thrusters(self, thrust_vector: list[float]) -> None:
        thrust_vector = self._correct_spin_direction(thrust_vector)
        thrust_vector = np.clip(thrust_vector, -1, 1)
        thrust_vector = self._reorder_thrust_vector(thrust_vector)
