from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
import time
import struct
import numpy as np
from serial.aio import Serial

if TYPE_CHECKING:
    from rov_state import RovState

INPUT_START_BYTE = 0x5A
NUM_MOTORS = 8
NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000
TIMEOUT_MS = 200


class Thrusters:
    def __init__(self, state: RovState, serial: Serial):
        self.state: RovState = state
        self.serial: Serial = serial

    async def send_loop(self) -> None:
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
