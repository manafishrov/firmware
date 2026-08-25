import asyncio
import copy
import json
from typing import Any, cast

from websockets import ServerConnection

from tools import mock_websocket_server


class _MockConnection:
    remote_address = ("127.0.0.1", 9000)

    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        self._incoming = iter(incoming)
        self.events: list[tuple[str, Any]] = []

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            message = next(self._incoming)
        except StopIteration as error:
            raise StopAsyncIteration from error
        self.events.append(("receive", message["type"]))
        return json.dumps(message)

    async def send(self, message: str) -> None:
        parsed = cast(dict[str, Any], json.loads(message))
        self.events.append(("send", parsed))

    async def close(self, *, reason: str) -> None:
        self.events.append(("close", reason))


def test_connection_success_toast_follows_matching_confirmation():
    original_config = copy.deepcopy(mock_websocket_server.MOCK_CONFIG)
    connection = _MockConnection(
        [
            {
                "type": "setConfig",
                "payload": {
                    "mutationId": "connection-1",
                    "config": {"ipAddress": "10.10.10.9"},
                },
            },
            {"type": "confirmConfig", "payload": "connection-1"},
        ]
    )

    try:
        asyncio.run(
            mock_websocket_server._handle_client(cast(ServerConnection, connection))
        )
    finally:
        mock_websocket_server.MOCK_CONFIG.clear()
        mock_websocket_server.MOCK_CONFIG.update(original_config)

    confirmation_index = connection.events.index(("receive", "confirmConfig"))
    success_index = next(
        index
        for index, event in enumerate(connection.events)
        if event[0] == "send"
        and event[1].get("type") == "showToast"
        and event[1]["payload"]["content"]["messageKey"]
        == "toasts_rov_config_set_successfully"
    )
    close_index = next(
        index for index, event in enumerate(connection.events) if event[0] == "close"
    )

    assert confirmation_index < success_index < close_index
