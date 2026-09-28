import asyncio
import json
from unittest.mock import Mock

from pydantic import TypeAdapter, ValidationError
import pytest
import websockets

from rov_firmware.websocket.message import WebsocketMessage
from rov_firmware.websocket.server import WebsocketServer


def test_obsolete_runtime_messages_are_not_a_second_control_interface():
    adapter = TypeAdapter(WebsocketMessage)
    for kind, payload in [
        ("customAction", "water_sensor"),
        ("setDepthHold", True),
        ("directionVector", [0] * 8),
        ("telemetry", {}),
    ]:
        with pytest.raises(ValidationError):
            adapter.validate_python({"type": kind, "payload": payload})


def test_real_websocket_catalog_and_correlated_errors(rov_state):
    async def scenario():
        instance = WebsocketServer(rov_state, Mock())
        async with websockets.serve(instance.handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as client:
                await client.send(
                    json.dumps(
                        {
                            "type": "capabilityRequest",
                            "payload": {
                                "version": 1,
                                "requestId": "catalog",
                                "operation": "catalog.get",
                                "params": {},
                            },
                        }
                    )
                )
                async with asyncio.timeout(5):
                    while True:
                        frame = json.loads(await client.recv())
                        assert frame["type"] not in ("telemetry", "statusUpdate")
                        if frame["type"] == "capabilityResponse":
                            break
                assert frame["payload"]["requestId"] == "catalog"
                assert frame["payload"]["ok"]
                assert frame["payload"]["result"]["samples"]
                await client.send(
                    json.dumps(
                        {
                            "type": "capabilityRequest",
                            "payload": {
                                "version": 99,
                                "requestId": "invalid",
                                "operation": "catalog.get",
                                "params": {},
                            },
                        }
                    )
                )
                async with asyncio.timeout(5):
                    while True:
                        frame = json.loads(await client.recv())
                        if frame["type"] == "capabilityResponse":
                            break
                assert frame["payload"]["requestId"] == "invalid"
                assert not frame["payload"]["ok"]
                assert frame["payload"]["error"]["code"] == "invalid_request"
        await instance.capabilities.shutdown()

    asyncio.run(scenario())
