_is_client_connected: bool = False


def set_log_is_client_connected_status(is_connected: bool) -> None:
    global _is_client_connected
    _is_client_connected = is_connected


async def log_info(message: str) -> None:
    if _is_client_connected:
        from websocket_server import get_message_queue

        await get_message_queue().put(
            {
                "type": "logMessage",
                "payload": {"origin": "firmware", "level": "info", "message": message},
            }
        )
    else:
        print(f"INFO: {message}")


async def log_warn(message: str) -> None:
    if _is_client_connected:
        from websocket_server import get_message_queue

        await get_message_queue().put(
            {
                "type": "logMessage",
                "payload": {"origin": "firmware", "level": "info", "message": message},
            }
        )
    else:
        print(f"INFO: {message}")


async def log_error(message: str) -> None:
    if _is_client_connected:
        from websocket_server import get_message_queue

        await get_message_queue().put(
            {
                "type": "logMessage",
                "payload": {"origin": "firmware", "level": "info", "message": message},
            }
        )
    else:
        print(f"INFO: {message}")
