from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
import time
import struct
import glob
import sys
import numpy as np
from serial.aio import Serial
from log import log_error

if TYPE_CHECKING:
    from rov_state import RovState

INPUT_START_BYTE = 0x5A
TELEMETRY_START_BYTE = 0xA5
NUM_MOTORS = 8
NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000
TIMEOUT_MS = 200


class Thrusters:
    def __init__(self, state: RovState):
        self.state: RovState = state
        self.serial: Serial | None = None

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
        serial_port = await self._find_pico_port()
        self.serial = Serial(serial_port, baudrate=115200)
        await self.serial.open()

    def start_tasks(self) -> None:
        asyncio.create_task(self._send_task())
        asyncio.create_task(self._receive_task())

    async def _send_task(self) -> None:
        assert self.serial is not None
        last_thrust = np.zeros(NUM_MOTORS)
        last_send_time = time.time()
        while True:
            current_time = time.time()
            if (
                self.state.direction_vector is not None
                and current_time - self.state.last_direction_time < TIMEOUT_MS / 1000
            ):
                imu_data = self.state.imu
                last_thrust = self.state.direction_vector
                last_send_time = current_time
            elif current_time - last_send_time > TIMEOUT_MS / 1000:
                last_thrust = np.zeros(NUM_MOTORS)
            thrust_values = []
            for val in last_thrust:
                if val >= 0:
                    thruster_val = int(NEUTRAL + val * FORWARD_RANGE)
                else:
                    thruster_val = int(NEUTRAL + val * REVERSE_RANGE)
                thrust_values.append(thruster_val)
            thrust_values = (thrust_values + [NEUTRAL] * NUM_MOTORS)[:NUM_MOTORS]
            data_payload = struct.pack(f"<{NUM_MOTORS}H", *thrust_values)
            packet = bytearray([INPUT_START_BYTE]) + data_payload
            checksum = 0
            for b in packet:
                checksum ^= b
            packet.append(checksum)
            await self.serial.write(packet)
            await asyncio.sleep(1 / 60)

    async def _receive_task(self) -> None:
        assert self.serial is not None
        read_buffer = bytearray()
        while True:
            data = await self.serial.read(1)
            if data:
                read_buffer.extend(data)
                while len(read_buffer) >= 8:
                    start_idx = read_buffer.find(
                        TELEMETRY_START_BYTE.to_bytes(1, "big")
                    )
                    if start_idx == -1:
                        if len(read_buffer) > 16:
                            read_buffer = bytearray()
                        break
                    if start_idx > 0:
                        read_buffer = read_buffer[start_idx:]
                    if len(read_buffer) >= 8:
                        packet = read_buffer[:8]
                        if self._validate_telemetry_packet(packet):
                            self._update_telemetry(packet)
                        read_buffer = read_buffer[8:]
                    else:
                        break

    def _validate_telemetry_packet(self, packet: bytearray) -> bool:
        if len(packet) != 8 or packet[0] != TELEMETRY_START_BYTE:
            return False
        calculated_checksum = 0
        for b in packet[:7]:
            calculated_checksum ^= b
        return calculated_checksum == packet[7]

    def _update_telemetry(self, packet: bytearray) -> None:
        global_id = packet[1]
        packet_type = packet[2]
        value = struct.unpack("<i", packet[3:7])[0]
        if 0 <= global_id < 8:
            if packet_type == 0:
                erpm = list(self.state.esc.erpm)
                erpm[global_id] = value
                self.state.esc.erpm = tuple(erpm)
            elif packet_type == 1:
                voltage = list(self.state.esc.voltage_cv)
                voltage[global_id] = value
                self.state.esc.voltage_cv = tuple(voltage)
            elif packet_type == 2:
                temp = list(self.state.esc.temperature)
                temp[global_id] = value
                self.state.esc.temperature = tuple(temp)
            elif packet_type == 3:
                current = list(self.state.esc.current_ca)
                current[global_id] = value
                self.state.esc.current_ca = tuple(current)

    async def shutdown(self) -> None:
        if self.serial:
            await self.serial.close()
