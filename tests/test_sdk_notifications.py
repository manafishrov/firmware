"""Plain notifications use the same firmware toast delivery and stop semantics."""

import asyncio

import pytest

from manafish_sdk import Context, NotificationLevel
from rov_firmware.extensions.csv_store import CsvStore
from rov_firmware.models.toast import ToastVariant


def test_notification_plain_text_severity_and_namespaced_replacement(
    rov_state, tmp_path, monkeypatch
):
    delivered = []
    monkeypatch.setattr(
        "rov_firmware.extensions.sdk.toast_content", lambda **kw: delivered.append(kw)
    )
    context = Context(rov_state, lambda *_: None, CsvStore(tmp_path), "sensor")
    asyncio.run(
        context.notify(
            "Water detected",
            level=NotificationLevel.WARNING,
            description="Check housing",
            key="wet",
        )
    )
    message = delivered[0]
    assert message["identifier"] == "custom-action:sensor:wet"
    assert message["variant"] == ToastVariant.WARN
    assert message["content"].message == "Water detected"
    assert message["content"].description == "Check housing"
    assert message["content"].message_key == ""
    assert message["action"] is None
    context.close()
    with pytest.raises(RuntimeError, match="stopped"):
        asyncio.run(context.notify("Late message"))
    assert len(delivered) == 1


def test_empty_notification_is_rejected(rov_state, tmp_path):
    context = Context(rov_state, lambda *_: None, CsvStore(tmp_path), "sensor")
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(context.notify("  "))
