import asyncio

from tools.mock_esc_firmware import TARGET_VERSION, MockEscFirmware


def test_mock_esc_flash_is_shared_and_telemetry_authoritative():
    messages: list[dict] = []

    async def run_test():
        mock = MockEscFirmware(flash_duration_seconds=0.01)

        async def send(message):
            messages.append(message)

        assert await mock.start(send)
        assert not await mock.start(send)
        while mock.active:
            await asyncio.sleep(0.01)

        assert mock.update.stage == "awaitingTelemetry"
        assert mock.versions == [TARGET_VERSION] * 8
        versions, payload = mock.status_payload()
        assert versions == [TARGET_VERSION] * 8
        assert payload["stage"] == "succeeded"

    asyncio.run(run_test())
    assert any(message["payload"]["variant"] == "success" for message in messages)


def test_mock_esc_flash_survives_initiating_client_disconnect():
    async def run_test():
        mock = MockEscFirmware(flash_duration_seconds=0.01)

        async def disconnected_sender(_message):
            msg = "client disconnected"
            raise ConnectionError(msg)

        assert await mock.start(disconnected_sender)
        while mock.active:
            await asyncio.sleep(0.01)

        assert mock.update.stage == "awaitingTelemetry"
        versions, payload = mock.status_payload()
        assert versions == [TARGET_VERSION] * 8
        assert payload["stage"] == "succeeded"

    asyncio.run(run_test())
