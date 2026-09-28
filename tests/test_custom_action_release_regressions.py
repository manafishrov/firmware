"""Safety and lifecycle regressions found during RC review."""

import asyncio
import importlib
from unittest.mock import AsyncMock, Mock

import pytest

from rov_firmware.custom_actions import builtins
from rov_firmware.custom_actions.runtime import CustomActionRuntime


@pytest.mark.parametrize("target", [0.0, 5.0])
def test_depth_targets_are_blocked_during_firmware_operations(
    rov_state, monkeypatch, target
):
    monkeypatch.setattr(
        builtins, "motor_firmware_operation_blocker", lambda _: "Firmware busy"
    )
    handler = AsyncMock()
    monkeypatch.setattr(builtins, "handle_set_desired_depth", handler)
    with pytest.raises(ValueError, match="Firmware busy"):
        asyncio.run(builtins.invoke(rov_state, "rov.desiredDepth.set", target))
    handler.assert_not_awaited()


@pytest.mark.parametrize(
    "identifier,handler_name",
    [
        ("rov.depthHold.set", "handle_set_depth_hold"),
        ("rov.autoStabilization.set", "handle_set_auto_stabilization"),
    ],
)
def test_safety_blocker_still_allows_disabling_controls(
    rov_state, monkeypatch, identifier, handler_name
):
    monkeypatch.setattr(
        builtins, "motor_firmware_operation_blocker", lambda _: "Firmware busy"
    )
    handler = AsyncMock()
    monkeypatch.setattr(builtins, handler_name, handler)
    asyncio.run(builtins.invoke(rov_state, identifier, False))
    handler.assert_awaited_once_with(rov_state, False)
    with pytest.raises(ValueError, match="Firmware busy"):
        asyncio.run(builtins.invoke(rov_state, identifier, True))


def test_connect_during_enable_waits_for_single_runner(
    rov_state, tmp_path, monkeypatch
):
    runtime = CustomActionRuntime(rov_state, tmp_path / "custom_actions")

    async def scenario():
        await runtime.install(
            'from manafish_sdk import Script\nscript = Script("test")\n'
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original = runtime._preparation.take

        async def delayed_take(source):
            entered.set()
            await release.wait()
            return await original(source)

        take = AsyncMock(side_effect=delayed_take)
        monkeypatch.setattr(runtime._preparation, "take", take)
        enabling = asyncio.create_task(runtime.enable("test", True))
        await entered.wait()
        connecting = asyncio.create_task(runtime.connected())
        try:
            await asyncio.sleep(0)
            assert not connecting.done()
            release.set()
            await asyncio.gather(enabling, connecting)
            take.assert_awaited_once()
            runner = runtime.runners["test"]
            await runtime._start("test")
            assert runtime.runners["test"] is runner
            take.assert_awaited_once()
        finally:
            release.set()
            await asyncio.gather(enabling, connecting, return_exceptions=True)
            await runtime.shutdown()

    asyncio.run(scenario())


def test_serial_shutdown_runs_even_if_custom_action_shutdown_fails(monkeypatch):
    firmware_main = importlib.import_module("rov_firmware.main")
    serial = Mock(shutdown=AsyncMock())
    server = Mock(
        initialize=AsyncMock(side_effect=ValueError("startup failed")),
        send_log_now=AsyncMock(),
        capabilities=Mock(
            shutdown=AsyncMock(side_effect=RuntimeError("cleanup failed"))
        ),
    )
    for name in ("RovState", "PressureSensor", "McuSensor", "PicoControl"):
        monkeypatch.setattr(firmware_main, name, Mock())
    monkeypatch.setattr(firmware_main, "SerialManager", Mock(return_value=serial))
    monkeypatch.setattr(firmware_main, "WebsocketServer", Mock(return_value=server))
    with pytest.raises(RuntimeError, match="cleanup failed"):
        asyncio.run(firmware_main.main())
    serial.shutdown.assert_awaited_once()
