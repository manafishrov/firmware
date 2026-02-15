"""This script tests thruster control and ESC telemetry by spinning all 8 thrusters at 10% forward and logging telemetry data."""

import asyncio
import logging
from pathlib import Path
import struct

from serial_asyncio_fast import open_serial_connection


ESC_MAX_READ_BUFFER_SIZE = 16
ESC_PACKET_TYPE_ERPM = 0
ESC_PACKET_TYPE_VOLTAGE = 1
ESC_PACKET_TYPE_TEMPERATURE = 2
ESC_PACKET_TYPE_CURRENT = 3
ESC_PACKET_TYPE_STRESS = 4
ESC_TELEMETRY_PACKET_SIZE = 8
ESC_TELEMETRY_START_BYTE = 0xA5
NUM_MOTORS = 8
THRUSTER_FORWARD_PULSE_RANGE = 1000
THRUSTER_INPUT_START_BYTE = 0x5A
THRUSTER_NEUTRAL_PULSE_WIDTH = 1000

erpm_count = [0]


def _find_port() -> str:
    """Find the microcontroller serial port."""
    ports = list(Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*"))
    if not ports:
        ports = list(Path("/dev/").glob("ttyACM*"))
    if ports:
        return str(ports[0])
    msg = "No microcontroller port found"
    raise RuntimeError(msg)


async def _send_thruster_loop(writer: asyncio.StreamWriter) -> None:
    """Send thruster commands to spin all motors at 10% forward."""
    thrust_value = THRUSTER_NEUTRAL_PULSE_WIDTH + int(
        0.1 * THRUSTER_FORWARD_PULSE_RANGE
    )
    values = [thrust_value] * NUM_MOTORS
    data_payload = struct.pack(f"<{NUM_MOTORS}H", *values)
    packet = bytearray([THRUSTER_INPUT_START_BYTE]) + data_payload
    checksum = 0
    for b in packet:
        checksum ^= b
    packet.append(checksum)
    while True:
        writer.write(packet)
        await asyncio.sleep(1 / 60)


async def _read_telemetry_loop(
    reader: asyncio.StreamReader, logger: logging.Logger
) -> None:
    """Read and log ESC telemetry data."""
    read_buffer = bytearray()
    while True:
        data = await reader.read(1)
        if data:
            read_buffer.extend(data)
            while len(read_buffer) >= ESC_TELEMETRY_PACKET_SIZE:
                start_idx = read_buffer.find(
                    ESC_TELEMETRY_START_BYTE.to_bytes(1, "big")
                )
                if start_idx == -1:
                    if len(read_buffer) > ESC_MAX_READ_BUFFER_SIZE:
                        read_buffer = bytearray()
                    break
                if start_idx > 0:
                    read_buffer = read_buffer[start_idx:]
                if len(read_buffer) >= ESC_TELEMETRY_PACKET_SIZE:
                    packet = read_buffer[:ESC_TELEMETRY_PACKET_SIZE]
                    if _validate_telemetry_packet(packet):
                        _log_telemetry(packet, logger)
                    read_buffer = read_buffer[ESC_TELEMETRY_PACKET_SIZE:]
                else:
                    break


def _validate_telemetry_packet(packet: bytearray) -> bool:
    """Validate the telemetry packet."""
    if (
        len(packet) != ESC_TELEMETRY_PACKET_SIZE
        or packet[0] != ESC_TELEMETRY_START_BYTE
    ):
        return False
    calculated_checksum = 0
    for b in packet[:7]:
        calculated_checksum ^= b
    return calculated_checksum == packet[7]


def _log_telemetry(packet: bytearray, logger: logging.Logger) -> None:
    """Log the telemetry data."""
    global_id = packet[1]
    packet_type = packet[2]
    value = struct.unpack("<i", packet[3:7])[0]
    if packet_type == ESC_PACKET_TYPE_ERPM:
        erpm_count[0] += 1
        if erpm_count[0] % 100 != 0:
            return
        type_str = "ERPM"
    elif packet_type == ESC_PACKET_TYPE_VOLTAGE:
        type_str = "Voltage"
    elif packet_type == ESC_PACKET_TYPE_TEMPERATURE:
        type_str = "Temperature"
    elif packet_type == ESC_PACKET_TYPE_CURRENT:
        type_str = "Current"
    elif packet_type == ESC_PACKET_TYPE_STRESS:
        type_str = "Stress"
    else:
        type_str = "Unknown"
    logger.info(f"Motor {global_id}: {type_str} = {value}")


async def main() -> None:
    """Run the thruster test script."""
    logger = logging.getLogger(__name__)
    port = _find_port()
    reader, writer = await open_serial_connection(url=port, baudrate=115200)
    try:
        _ = await asyncio.gather(
            _send_thruster_loop(writer), _read_telemetry_loop(reader, logger)
        )
    except KeyboardInterrupt:
        pass
    finally:
        writer.close()
        await writer.wait_closed()
