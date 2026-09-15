"""Main entry point for the ROV firmware."""

import asyncio
import contextlib
import traceback

from serial import SerialException

from .diagnostics import FieldDiagnostics
from .log import log_error
from .models.log import LogLevel
from .pico_control import PicoControl
from .rov_state import RovState
from .sensors.mcu import McuSensor
from .sensors.pressure import PressureSensor
from .serial import SerialManager
from .websocket.server import WebsocketServer


def _exception_handler(
    loop: asyncio.AbstractEventLoop, context: dict[str, object]
) -> None:
    exception = context.get("exception")
    if isinstance(exception, SerialException):
        return
    with contextlib.suppress(Exception):
        log_error(_format_asyncio_context(context))
    loop.default_exception_handler(context)


def _format_asyncio_context(context: dict[str, object]) -> str:
    message = str(context.get("message", "Unhandled exception in asyncio task"))
    exception = context.get("exception")
    if isinstance(exception, BaseException):
        tb = "".join(
            traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        )
        return f"{message}\n{tb}"
    return message


async def main() -> None:
    """Run the main ROV firmware loop."""
    asyncio.get_running_loop().set_exception_handler(_exception_handler)

    state: RovState = RovState()
    serial_manager: SerialManager = SerialManager(state)
    ws_server: WebsocketServer = WebsocketServer(state, serial_manager)
    pressure: PressureSensor = PressureSensor(state)
    mcu: McuSensor = McuSensor(state, serial_manager)
    control = PicoControl(state, serial_manager)
    state.pico = control

    tasks: list[asyncio.Task[None]] = []
    try:
        await ws_server.initialize()
        _ = await serial_manager.initialize()
        await pressure.initialize()

        tasks = [
            asyncio.create_task(pressure.read_loop(), name="pressure.read_loop"),
            asyncio.create_task(mcu.read_loop(), name="mcu.read_loop"),
            asyncio.create_task(control.send_loop(), name="pico_control.send_loop"),
            asyncio.create_task(ws_server.wait_closed(), name="ws_server.wait_closed"),
            asyncio.create_task(
                FieldDiagnostics(state, serial_manager, mcu, control).run(),
                name="field_diagnostics",
            ),
        ]
        _ = await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Send the crash to the app log before tearing down the connection.
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        await ws_server.send_log_now(LogLevel.ERROR, tb)
        raise
    finally:
        for task in tasks:
            _ = task.cancel()
        if tasks:
            _ = await asyncio.gather(*tasks, return_exceptions=True)
        await serial_manager.shutdown()
