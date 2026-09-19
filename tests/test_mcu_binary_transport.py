"""Exercise the upload boundary with binary-valued lengths and sequence bytes."""

import asyncio
from functools import reduce
from operator import xor
import struct
from typing import cast

import pytest

from rov_firmware import esc_firmware
from rov_firmware.sensors.mcu import McuSensor


class _PicoStagingTransport:
    """Replay staging ACKs only; reject any command that could program an ESC."""

    def __init__(self, reader: asyncio.StreamReader, *, crlf: bool):
        self.reader = reader
        self.crlf = crlf
        self.offset = 0
        self.sequence = 0
        self.payload = bytearray()

    def write(self, packet: bytes) -> None:
        assert reduce(xor, packet[:-1], 0) == packet[-1]
        if packet[0] == 0xE7:
            transaction = packet[2]
            if packet[1] == 1:  # BEGIN: RAM staging only
                self.offset = 0
                self.sequence = 0
                self.payload.clear()
                status = 1
                value = struct.unpack_from("<H", packet, 3)[0]
            else:
                assert packet[1] == 5, "Only BEGIN and QUERY_OFFSET are permitted"
                status = 2
                value = self.offset
        else:
            assert packet[0] == 0xE8
            transaction = packet[1]
            sequence, offset, length = struct.unpack_from("<HHB", packet, 2)
            chunk = packet[7 : 7 + length]
            if sequence == self.sequence:
                assert offset + length == self.offset
                assert self.payload[offset : offset + length] == chunk
            else:
                assert sequence == self.sequence + 1
                assert offset == self.offset
                self.payload.extend(chunk)
                self.sequence = sequence
                self.offset += length
            status = 2
            value = self.offset
        ack = struct.pack(
            "<BBBBIBH", 0xE9, status, 0xFF, 0, value, transaction, self.sequence
        )
        ack += bytes((reduce(xor, ack, 0),))
        self.reader.feed_data(ack.replace(b"\n", b"\r\n") if self.crlf else ack)

    async def drain(self) -> None:
        pass


@pytest.mark.parametrize("crlf", [True, False])
def test_full_upload_requires_binary_output_including_tenth_ack(monkeypatch, crlf):
    monkeypatch.setattr(esc_firmware, "_UPLOAD_ACK_TIMEOUT_S", 0.01)
    events = []
    monkeypatch.setattr(
        esc_firmware,
        "log_diagnostic",
        lambda event, **fields: events.append((event, fields)),
    )
    image = bytes(range(256)) * 108  # Exact 27,648-byte application region.

    async def run():
        reader = asyncio.StreamReader()
        transport = _PicoStagingTransport(reader, crlf=crlf)
        upload = esc_firmware._upload_image(
            reader,
            cast(asyncio.StreamWriter, transport),
            image,
            bytearray(),
            transaction_id=1,
        )
        if crlf:
            with pytest.raises(
                esc_firmware.EscFirmwareUpdateError,
                match=r"timed out at 504 bytes.*No ESC was modified",
            ):
                await upload
            assert transport.offset == 560  # Chunk arrived; its ACK was corrupted.
        else:
            await upload
            assert transport.payload == image
            assert transport.sequence == 494

    asyncio.run(run())
    if crlf:
        retries = [fields for event, fields in events if event == "esc_upload_retry"]
        assert len(retries) == 3
        assert retries[-1] == {
            "transaction": 1,
            "sequence": 10,
            "last_acknowledged_bytes": 504,
            "expected_bytes": 560,
            "attempt": 3,
        }
        corrupt = [fields for event, fields in events if event == "esc_status_timeout"]
        assert any("0d0a" in (fields["last_invalid_hex"] or "") for fields in corrupt)
    else:
        acks = [fields for event, fields in events if event == "esc_upload_ack"]
        assert acks[-1]["acknowledged_bytes"] == len(image)
        assert len(acks) < 16  # No per-chunk log flood.
        assert all(fields["commit_sent"] is False for fields in acks)


def test_ten_byte_release_identity_requires_binary_output():
    packet = bytes.fromhex("d6 01 0a 31 2e 30 2e 33 2d 72 63 2e 35 c8")
    assert McuSensor._validate_release_version_packet(packet)
    assert not McuSensor._validate_release_version_packet(
        packet.replace(b"\n", b"\r\n")
    )


def test_protocol_ack_request_ten_requires_binary_output():
    packet = bytes.fromhex("d5 0a 02 00 01 2c 01 f1")
    assert McuSensor._validate_runtime_config_status_packet(packet)
    assert not McuSensor._validate_runtime_config_status_packet(
        packet.replace(b"\n", b"\r\n")
    )
