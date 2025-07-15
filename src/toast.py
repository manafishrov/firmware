import asyncio
import json
from websocket_server import get_websocket_queue

async def send_toast(toast_type: str, message: str, description: str = None):
    await get_websocket_queue().put({
        "type": "showToast",
        "payload": {
            "toastType": toast_type,
            "message": message,
            "description": description,
        }
    })

