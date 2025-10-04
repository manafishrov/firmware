from __future__ import annotations

import asyncio
from .rov_state import RovState
from .websocket.server import WebsocketServer
from .websocket.senders import WebsocketSenders
from .log import log_info


async def main() -> None:
    state = RovState()
    ws_server = WebsocketServer(state)
    senders = WebsocketSenders(state, ws_server)

    await ws_server.start()
    message_sender_task = asyncio.create_task(senders.message_sender())

    await state.thrusters.initialize()

    tasks = [
        ws_server.wait_closed(),
        senders.telemetry_sender(),
        senders.status_update_sender(),
        message_sender_task,
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(log_info("Starting ROV Firmware..."))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(log_info("Shutting down."))
