from __future__ import annotations

import asyncio
from .rov_state import RovState
from .websocket.server import WebsocketServer
from .log import log_info


async def main() -> None:
    state = RovState()
    ws_server = WebsocketServer(state)

    await ws_server.start()

    tasks = [
        ws_server.wait_closed(),
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
