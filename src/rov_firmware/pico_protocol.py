"""Bounded, explicitly packed Pico control v1 wire format (no native structs)."""

from dataclasses import dataclass
import math
import struct

import numpy as np

from .models.config import RovConfig


START = 0xF0
VERSION = 1
MAX_PAYLOAD = 768
SETTINGS_SIZE = 628
MAX_NULLSPACE = 8
MAX_POWER = 100
CAPABILITY_HEADER_SIZE = 12
ACK_SIZE = 12
ATTITUDE_SIZE = 84
IMU_SIZE = 28
STATS_SIZE = 48
FRAME_TIMEOUT = 0.1
REQUIRED_FEATURES = 15
ENTER_MAINTENANCE = 0x25
HEADER = struct.Struct("<BBBBHII")
OVERHEAD = HEADER.size + 4
HELLO = 0x01
CONTROL = 0x10
PRESSURE = 0x11
SET_ATTITUDE = 0x12
SET_DEPTH = 0x13
RAW_MOTORS = 0x14
BEGIN = 0x20
CHUNK = 0x21
COMMIT = 0x22
ABORT = 0x23
QUERY = 0x24
ACK = 0x80
CAPABILITIES = 0x81
ATTITUDE = 0x90
STATS = 0x91
IMU = 0x92
APPLIED = 0
STAGED = 1


def crc32c(data: bytes | bytearray) -> int:
    """Castagnoli reflected CRC, initial/final XOR all ones."""
    crc = 0xFFFFFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


@dataclass(frozen=True)
class Frame:
    """A CRC-verified frame; sequences are scoped to a negotiated session."""

    kind: int
    session: int
    sequence: int
    payload: bytes

    def encode(self) -> bytes:
        """Serialize a single bounded frame."""
        if len(self.payload) > MAX_PAYLOAD:
            msg = "Pico payload exceeds negotiated bound"
            raise ValueError(msg)
        packet = (
            HEADER.pack(
                START,
                VERSION,
                self.kind,
                0,
                len(self.payload),
                self.session,
                self.sequence,
            )
            + self.payload
        )
        return packet + struct.pack("<I", crc32c(packet))


def decode(packet: bytes) -> Frame:
    """Validate before dispatch; embedded legacy tokens remain opaque."""
    if len(packet) < OVERHEAD:
        msg = "Truncated Pico frame"
        raise ValueError(msg)
    start, version, kind, flags, length, session, sequence = HEADER.unpack_from(packet)
    if (
        start != START
        or version != VERSION
        or flags != 0
        or length > MAX_PAYLOAD
        or len(packet) != length + OVERHEAD
        or crc32c(packet[:-4]) != struct.unpack_from("<I", packet, len(packet) - 4)[0]
    ):
        msg = "Invalid Pico frame"
        raise ValueError(msg)
    return Frame(kind, session, sequence, packet[HEADER.size : -4])


def settings_image(config: RovConfig) -> bytes:
    """Encode every Pico-owned setting, including protocol, as one atomic image."""
    regulator = config.regulator
    axes = (regulator.roll, regulator.pitch, regulator.yaw, regulator.depth)
    values = [
        value for axis in axes for value in (axis.kp, axis.ki, axis.kd, axis.rate)
    ]
    power = config.power
    limits = (power.thrusters_limit, power.actions_limit, power.regulator_limit)
    coeff = config.direction_coefficients
    coefficients = (coeff.surge, coeff.sway, coeff.heave)
    allocation = (
        np.asarray(config.thruster_allocation, dtype=np.float32).ravel().tolist()
    )
    nullspace = config.nullspace_vectors
    if len(nullspace) > MAX_NULLSPACE:
        msg = "Pico supports at most 8 nullspace vectors; none were applied"
        raise ValueError(msg)
    nv = [float(value) for row in nullspace for value in row]
    if not all(
        math.isfinite(value) for value in (*values, *coefficients, *allocation, *nv)
    ):
        msg = "Pico settings must contain only finite values"
        raise ValueError(msg)
    if any(value < 0 or value > MAX_POWER for value in limits):
        msg = "Pico power limits must be between 0 and 100"
        raise ValueError(msg)
    identifiers = config.thruster_pin_setup.identifiers.tolist()
    spin = config.thruster_pin_setup.spin_directions.tolist()
    if any(value not in range(8) for value in identifiers):
        msg = "Thruster identifiers must be 0..7"
        raise ValueError(msg)
    if any(value not in (-1, 1) for value in spin):
        msg = "Spin directions must be -1 or +1"
        raise ValueError(msg)
    image = struct.pack(
        "<16fI3f3f64f8B8bI64fHH",
        *values,
        int(regulator.fpv_mode),
        *limits,
        *coefficients,
        *allocation,
        *identifiers,
        *spin,
        len(nullspace),
        *nv,
        *([0.0] * (64 - len(nv))),
        int(config.thruster_protocol == "dshot"),
        config.dshot_speed,
    )
    if len(image) != SETTINGS_SIZE:
        msg = "Unexpected Pico settings image size"
        raise ValueError(msg)
    return image
