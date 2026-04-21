"""This script tests thruster control and MCU telemetry by spinning all 8 thrusters at 10% forward and logging telemetry data."""

import asyncio
import logging
from pathlib import Path
import struct

from serial_asyncio_fast import open_serial_connection


MCU_TELEMETRY_MAX_READ_BUFFER_SIZE = 16
MCU_TELEMETRY_BATCH_HEADER_SIZE = 2
MCU_TELEMETRY_BATCH_ENTRY_SIZE = 6
MCU_TELEMETRY_BATCH_MAX_ITEMS = 16
MCU_TELEMETRY_BATCH_MIN_PACKET_SIZE = 3
MCU_TELEMETRY_BATCH_START_BYTE = 0xA6
MCU_TELEMETRY_TYPE_ERPM = 0
MCU_TELEMETRY_TYPE_VOLTAGE = 1
MCU_TELEMETRY_TYPE_TEMPERATURE = 2
MCU_TELEMETRY_TYPE_CURRENT = 3
MCU_TELEMETRY_TYPE_SIGNAL_QUALITY = 4
MCU_TELEMETRY_PACKET_SIZE = 8
MCU_TELEMETRY_START_BYTE = 0xA5
NUM_MOTORS = 8
THRUSTER_FORWARD_PULSE_RANGE = 1000
THRUSTER_INPUT_START_BYTE = 0x5A
THRUSTER_NEUTRAL_PULSE_WIDTH = 1000

erpm_count = [0]


def _find_port() -> str:
    """Find the MCU serial port."""
    ports = list(Path("/dev/serial/by-id/").glob("usb-Raspberry_Pi_Pico*"))
    if not ports:
        ports = list(Path("/dev/").glob("ttyACM*"))
    if ports:
        return str(ports[0])
    msg = "No MCU port found"
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
    """Read and log MCU telemetry data."""
    read_buffer = bytearray()
    while True:
        data = await reader.read(128)
        if data:
            read_buffer.extend(data)
            while True:
                start_idx = _find_start_byte(read_buffer)
                if start_idx == -1:
                    if len(read_buffer) > MCU_TELEMETRY_MAX_READ_BUFFER_SIZE:
                        read_buffer = bytearray()
                    break
                if start_idx > 0:
                    read_buffer = read_buffer[start_idx:]

                if not _consume_next_packet(read_buffer, logger):
                    break


def _find_start_byte(read_buffer: bytearray) -> int:
    candidates = (
        read_buffer.find(MCU_TELEMETRY_START_BYTE),
        read_buffer.find(MCU_TELEMETRY_BATCH_START_BYTE),
    )
    valid_candidates = [idx for idx in candidates if idx >= 0]
    if not valid_candidates:
        return -1
    return min(valid_candidates)


def _consume_next_packet(read_buffer: bytearray, logger: logging.Logger) -> bool:
    if not read_buffer:
        return False
    if read_buffer[0] == MCU_TELEMETRY_BATCH_START_BYTE:
        return _try_consume_telemetry_batch(read_buffer, logger)
    if read_buffer[0] == MCU_TELEMETRY_START_BYTE:
        return _try_consume_telemetry_packet(read_buffer, logger)
    del read_buffer[:1]
    return True


def _try_consume_telemetry_packet(
    read_buffer: bytearray, logger: logging.Logger
) -> bool:
    if len(read_buffer) < MCU_TELEMETRY_PACKET_SIZE:
        return False

    packet = read_buffer[:MCU_TELEMETRY_PACKET_SIZE]
    if _validate_telemetry_packet(packet):
        _log_telemetry(
            packet[1], packet[2], struct.unpack_from("<i", packet, 3)[0], logger
        )
    read_buffer[:] = read_buffer[MCU_TELEMETRY_PACKET_SIZE:]
    return True


def _try_consume_telemetry_batch(
    read_buffer: bytearray, logger: logging.Logger
) -> bool:
    if len(read_buffer) < MCU_TELEMETRY_BATCH_HEADER_SIZE:
        return False

    item_count = read_buffer[1]
    if item_count == 0 or item_count > MCU_TELEMETRY_BATCH_MAX_ITEMS:
        read_buffer[:] = read_buffer[1:]
        return True

    total_len = MCU_TELEMETRY_BATCH_MIN_PACKET_SIZE + (
        item_count * MCU_TELEMETRY_BATCH_ENTRY_SIZE
    )
    if len(read_buffer) < total_len:
        return False

    packet = read_buffer[:total_len]
    if _validate_telemetry_batch_packet(packet):
        offset = 2
        for _ in range(item_count):
            _log_telemetry(
                packet[offset],
                packet[offset + 1],
                struct.unpack_from("<i", packet, offset + 2)[0],
                logger,
            )
            offset += MCU_TELEMETRY_BATCH_ENTRY_SIZE

    read_buffer[:] = read_buffer[total_len:]
    return True


def _validate_telemetry_packet(packet: bytearray) -> bool:
    """Validate the telemetry packet."""
    if (
        len(packet) != MCU_TELEMETRY_PACKET_SIZE
        or packet[0] != MCU_TELEMETRY_START_BYTE
    ):
        return False
    calculated_checksum = 0
    for b in packet[:7]:
        calculated_checksum ^= b
    return calculated_checksum == packet[7]


def _validate_telemetry_batch_packet(packet: bytearray) -> bool:
    if (
        len(packet) < MCU_TELEMETRY_BATCH_MIN_PACKET_SIZE
        or packet[0] != MCU_TELEMETRY_BATCH_START_BYTE
    ):
        return False

    item_count = packet[1]
    expected_len = MCU_TELEMETRY_BATCH_MIN_PACKET_SIZE + (
        item_count * MCU_TELEMETRY_BATCH_ENTRY_SIZE
    )
    if item_count == 0 or item_count > MCU_TELEMETRY_BATCH_MAX_ITEMS:
        return False
    if len(packet) != expected_len:
        return False

    calculated_checksum = 0
    for b in packet[:-1]:
        calculated_checksum ^= b
    return calculated_checksum == packet[-1]


def _log_telemetry(
    global_id: int, packet_type: int, value: int, logger: logging.Logger
) -> None:
    """Log the telemetry data."""
    if packet_type == MCU_TELEMETRY_TYPE_ERPM:
        erpm_count[0] += 1
        if erpm_count[0] % 100 != 0:
            return
        type_str = "ERPM"
    elif packet_type == MCU_TELEMETRY_TYPE_VOLTAGE:
        type_str = "Voltage"
    elif packet_type == MCU_TELEMETRY_TYPE_TEMPERATURE:
        type_str = "Temperature"
    elif packet_type == MCU_TELEMETRY_TYPE_CURRENT:
        type_str = "Current"
    elif packet_type == MCU_TELEMETRY_TYPE_SIGNAL_QUALITY:
        type_str = "Signal Quality"
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
