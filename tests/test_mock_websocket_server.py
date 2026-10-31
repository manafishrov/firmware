import asyncio
import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from websockets import ServerConnection

from tools import mock_websocket_server


@pytest.fixture(autouse=True)
def isolated_mock(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        mock_websocket_server,
        "CAPABILITIES",
        mock_websocket_server.MockCapabilities(tmp_path),
    )
    monkeypatch.setattr(
        mock_websocket_server,
        "SYSTEM_STATUS",
        copy.deepcopy(mock_websocket_server.SYSTEM_STATUS),
    )


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

    def sent(self, message_type: str) -> list[dict[str, Any]]:
        return [
            event[1]
            for event in self.events
            if event[0] == "send" and event[1]["type"] == message_type
        ]


class _PacedConnection(_MockConnection):
    """Give background work a status period to run between client messages."""

    async def __anext__(self) -> str:
        await asyncio.sleep(mock_websocket_server.STATUS_PERIOD)
        return await super().__anext__()


def _invoke(request_id: str, identifier: str, value: Any = None) -> dict[str, Any]:
    return {
        "type": "capabilityRequest",
        "payload": {
            "version": 1,
            "requestId": request_id,
            "operation": "action.invoke",
            "params": {"id": identifier, "phase": "press", "value": value},
        },
    }


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


def test_connection_streams_the_firmware_capability_catalog():
    connection = _PacedConnection([])

    asyncio.run(
        mock_websocket_server._handle_client(cast(ServerConnection, connection))
    )

    sent_types = [event[1]["type"] for event in connection.events if event[0] == "send"]
    assert sent_types[:2] == ["config", "capabilityCatalog"]
    catalog = connection.sent("capabilityCatalog")[0]["payload"]
    assert catalog["version"] == 1
    assert "rov.direction" in {action["id"] for action in catalog["actions"]}
    assert "rov.depth" in {reading["id"] for reading in catalog["readings"]}
    sampled = {
        sample["id"]
        for message in connection.sent("capabilitySamples")
        for sample in message["payload"]["samples"]
    }
    assert {"rov.depth", "rov.batteryPercentage"} <= sampled


def test_builtin_actions_drive_the_simulation():
    connection = _PacedConnection(
        [
            _invoke("direction", "rov.direction", [0.5, 0, 0, 0, 0, 0, 0, 0]),
            _invoke("depth-hold", "rov.depthHold.toggle"),
            _invoke("unknown", "rov.unknown"),
        ]
    )

    asyncio.run(
        mock_websocket_server._handle_client(cast(ServerConnection, connection))
    )

    responses = {
        message["payload"]["requestId"]: message["payload"]
        for message in connection.sent("capabilityResponse")
    }
    assert responses["direction"]["ok"]
    assert responses["depth-hold"]["ok"]
    assert not responses["unknown"]["ok"]
    assert mock_websocket_server.SYSTEM_STATUS["depthHold"]
    depth_hold_samples = [
        sample["value"]
        for message in connection.sent("capabilitySamples")
        for sample in message["payload"]["samples"]
        if sample["id"] == "rov.depthHold"
    ]
    assert depth_hold_samples[-1] is True
