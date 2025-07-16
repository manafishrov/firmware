import asyncio
from log import log_error
import numpy as np
from numpy.typing import NDArray
import struct
import serial
import glob
import sys
import time
import threading
from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from rov_state import ROVState


class Thrusters:
    def __init__(self, state: "ROVState"):
        self.state: "ROVState" = state
        self.erpms: list[float] = [0.0] * 8
        self.serial = None
        self._serial_lock = threading.Lock()

        self._telemetry_thread = None
        self._telemetry_thread_stop = threading.Event()

    def start_telemetry_listener(self):
        if self._telemetry_thread is None or not self._telemetry_thread.is_alive():
            self._telemetry_thread_stop.clear()
            self._telemetry_thread = threading.Thread(
                target=self._telemetry_reader, daemon=True
            )
            self._telemetry_thread.start()

    def stop_telemetry_listener(self):
        if self._telemetry_thread is not None:
            self._telemetry_thread_stop.set()
            self._telemetry_thread.join(timeout=2.0)

    def _telemetry_reader(self):
        TELEMETRY_START_BYTE = 0xA5
        TELEMETRY_PACKET_SIZE = 7
        try:
            if self.serial is None:
                return
            self.serial.timeout = 0.01
            read_buffer = b""
            while not self._telemetry_thread_stop.is_set():
                try:
                    with self._serial_lock:
                        new_bytes = self.serial.read(self.serial.in_waiting or 1)
                    if new_bytes:
                        read_buffer += new_bytes
                        while True:
                            start_index = read_buffer.find(
                                bytes([TELEMETRY_START_BYTE])
                            )
                            if start_index == -1:
                                if len(read_buffer) > TELEMETRY_PACKET_SIZE * 2:
                                    read_buffer = b""
                                break
                            if start_index > 0:
                                read_buffer = read_buffer[start_index:]
                            if len(read_buffer) >= TELEMETRY_PACKET_SIZE:
                                packet = read_buffer[:TELEMETRY_PACKET_SIZE]
                                if self._validate_and_update_erpm(packet):
                                    pass
                                read_buffer = read_buffer[TELEMETRY_PACKET_SIZE:]
                            else:
                                break
                    time.sleep(0.001)
                except Exception:
                    break
        except Exception:
            pass

    def _validate_and_update_erpm(self, pkt_bytes):
        import struct

        TELEMETRY_START_BYTE = 0xA5
        TELEMETRY_PACKET_SIZE = 7
        if len(pkt_bytes) != TELEMETRY_PACKET_SIZE:
            return False
        if pkt_bytes[0] != TELEMETRY_START_BYTE:
            return False

        def calculate_checksum(data_bytes):
            checksum = 0
            for byte in data_bytes:
                checksum ^= byte
            return checksum

        calculated_checksum = calculate_checksum(pkt_bytes[: TELEMETRY_PACKET_SIZE - 1])
        received_checksum = pkt_bytes[TELEMETRY_PACKET_SIZE - 1]
        if calculated_checksum != received_checksum:
            return False
        global_motor_id = pkt_bytes[1]
        erpm_value = struct.unpack("<i", pkt_bytes[2:6])[0]
        if 0 <= global_motor_id < len(self.erpms):
            self.erpms[global_motor_id] = erpm_value
        return True

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
            self.start_telemetry_listener()
        except Exception as e:
            await log_error(f"Error opening serial port: {e}")
            sys.exit(1)

    def _scale_vector_with_user_max_power(
        self, direction_vector: NDArray[np.float64]
    ) -> None:
        scale = self.state.rov_config["power"]["userMaxPower"]
        np.multiply(direction_vector, scale, out=direction_vector)

    def _create_thrust_vector_from_thruster_allocation(
        self, direction_vector: NDArray[np.float64]
    ) -> list[float]:
        allocation_matrix = np.array(
            self.state.rov_config["thrusterAllocation"], dtype=float
        )
        direction_vector_np = direction_vector.reshape(-1)
        # Match matrix to the direction vector input size
        cols = direction_vector_np.shape[0]
        allocation_matrix = allocation_matrix[:, :cols]
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

    def run_thrusters_with_regulator(
        self, direction_vector: NDArray[np.float64]
    ) -> None:
        self._scale_vector_with_user_max_power(direction_vector)
        thrust_vector = self._create_thrust_vector_from_thruster_allocation(
            direction_vector
        )
        self.run_thrusters(thrust_vector)

    def run_thrusters(self, thrust_vector: list[float], reorder: bool = True) -> None:
        thrust_vector = self._correct_spin_direction(thrust_vector)
        thrust_vector = np.clip(thrust_vector, -1, 1)
        if reorder:
            thrust_vector = self._reorder_thrust_vector(thrust_vector)
        INPUT_START_BYTE = 0x5A
        NUM_MOTORS = 8
        NEUTRAL = 1000
        FORWARD_RANGE = 1000
        REVERSE_RANGE = 1000

        thrust_values = []
        for val in thrust_vector:
            if val >= 0:
                thruster_val = int(NEUTRAL + val * FORWARD_RANGE)
            else:
                thruster_val = int(NEUTRAL + val * REVERSE_RANGE)
            thrust_values.append(thruster_val)

        thrust_values = (thrust_values + [NEUTRAL] * NUM_MOTORS)[:NUM_MOTORS]

        def calculate_checksum(data_bytes: Union[bytes, bytearray]) -> int:
            checksum = 0
            for byte in data_bytes:
                checksum ^= byte
            return checksum

        if self.serial is not None and self.serial.is_open:
            data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
            packet_without_checksum = bytearray([INPUT_START_BYTE]) + data_payload
            checksum = calculate_checksum(packet_without_checksum)
            full_packet = packet_without_checksum + bytearray([checksum])
            try:
                with self._serial_lock:
                    self.serial.write(full_packet)
            except Exception as e:

                asyncio.create_task(log_error(f"Error writing to thruster serial: {e}"))
        else:
            asyncio.create_task(
                log_error("Thruster serial port not open when trying to send thrust.")
            )

    def test_thruster(self, thruster_identifier: int) -> None:
        import time

        thrust_vector = [0.0] * 8
        if 0 <= thruster_identifier < len(thrust_vector):
            thrust_vector[thruster_identifier] = 0.05
            start_time = time.time()
            while (time.time() - start_time) < 5.0:
                self.run_thrusters(thrust_vector, reorder=False)
                time.sleep(0.02)
            self.run_thrusters([0.0] * 8, reorder=False)
        else:
            print(f"Invalid thruster identifier: {thruster_identifier}")
