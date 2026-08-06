import asyncio

from rov_firmware.serial import SerialManager
from rov_firmware.websocket import handler
from rov_firmware.websocket.message import FlashEscFirmware
from rov_firmware.websocket.server import websocket_message_adapter


def test_flash_esc_firmware_message_round_trips():
    message = websocket_message_adapter.validate_python({"type": "flashEscFirmware"})

    assert isinstance(message, FlashEscFirmware)
    assert message.model_dump(by_alias=True) == {"type": "flashEscFirmware"}


def test_flash_esc_firmware_message_runs_verified_updater(rov_state, monkeypatch):
    serial_manager = SerialManager(rov_state)
    calls = []

    async def fake_flash(state, manager, *, show_toasts):
        calls.append((state, manager, show_toasts))
        return True

    monkeypatch.setattr(handler, "flash_esc_firmware", fake_flash)
    message = websocket_message_adapter.validate_python({"type": "flashEscFirmware"})

    asyncio.run(handler.handle_message(rov_state, serial_manager, message))

    assert calls == [(rov_state, serial_manager, True)]
