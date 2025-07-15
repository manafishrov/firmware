import asyncio
import json
from websocket_server import get_websocket_queue

async def send_log(level: str, message: str):
    await get_websocket_queue().put({
        "type": "logMessage",
        "payload": {"level": level, "message": message}
    })

