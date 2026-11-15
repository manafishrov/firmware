"""A Pico waiting in BOOTSEL is flashed even if the first attempt fails."""

import asyncio

from rov_firmware.constants import (
    MCU_FIRST_BOOT_FLASH_ATTEMPTS,
    MCU_FIRST_BOOT_RETRY_LIMIT,
)
from rov_firmware.serial import SerialManager
from rov_firmware.websocket.receive import mcu


def _missing_mcu(rov_state, monkeypatch, results: list[bool]) -> list[int]:
    manager = SerialManager(rov_state)

    async def no_port(*, log_missing: bool = True) -> None:
        del log_missing

    monkeypatch.setattr(manager, "_find_mcu_port", no_port)
    flashes: list[int] = []

    async def flash(_state, _board, *, show_toasts: bool) -> bool:
        assert show_toasts
        flashes.append(lookups)
        return results.pop(0)

    monkeypatch.setattr(mcu, "flash_mcu_firmware", flash)
    lookups = 0

    async def run() -> None:
        nonlocal lookups
        while lookups < 6 * MCU_FIRST_BOOT_RETRY_LIMIT:
            lookups += 1
            assert not await manager.initialize(notify=False)

    asyncio.run(run())
    return flashes


def test_failed_first_boot_flash_is_retried_until_it_succeeds(rov_state, monkeypatch):
    flashes = _missing_mcu(rov_state, monkeypatch, [False, True])

    assert flashes == [MCU_FIRST_BOOT_RETRY_LIMIT, 2 * MCU_FIRST_BOOT_RETRY_LIMIT]


def test_first_boot_flash_attempts_are_capped(rov_state, monkeypatch):
    flashes = _missing_mcu(rov_state, monkeypatch, [False] * 10)

    assert len(flashes) == MCU_FIRST_BOOT_FLASH_ATTEMPTS
