"""Correlated V1 management API over the existing WebSocket envelope."""

import asyncio
from collections.abc import Callable
from typing import Any

from .runtime import CustomActionRuntime
from .source_bundle import source_bundle


async def dispatch(
    runtime: CustomActionRuntime, operation: str, params: dict[str, Any]
) -> object:
    """Dispatch supported operations; unavailable and invalid inputs fail clearly."""
    if operation in {"sdk.describe", "sdk.read"}:
        bundle = await asyncio.to_thread(source_bundle)
        return (
            bundle.describe()
            if operation == "sdk.describe"
            else bundle.read(params["revision"], params["offset"])
        )
    if operation == "catalog.get":
        runtime.refresh_builtins()
        return runtime.catalog()
    if operation == "action.invoke":
        return await runtime.invoke(
            params["id"], params.get("phase", "press"), params.get("value")
        )
    if operation == "action.configure":
        return await runtime.configure(
            params["id"], params["mode"], params["intervalMs"]
        )
    if operation.startswith("customAction."):
        return await _custom_action(runtime, operation, params)
    if operation.startswith("csv."):
        return await _csv(runtime, operation, params)
    msg = f"Unknown capability operation {operation}"
    raise ValueError(msg)


async def _custom_action(
    runtime: CustomActionRuntime, operation: str, params: dict[str, Any]
) -> object:
    if operation == "customAction.list":
        return [
            item.model_dump(by_alias=True) for item in runtime.custom_actions.values()
        ]
    if operation == "customAction.validate":
        return await runtime.validate(params["source"])
    if operation == "customAction.install":
        return await runtime.install(params["source"])
    if operation == "customAction.remove":
        return await runtime.remove(params["id"])
    if operation == "customAction.enable":
        if type(params["enabled"]) is not bool:
            msg = "enabled must be a boolean"
            raise ValueError(msg)
        return await runtime.enable(params["id"], params["enabled"])
    if operation == "customAction.source":
        identifier = params["id"]
        if identifier not in runtime.custom_actions:
            raise KeyError(identifier)
        return {
            "source": (runtime.directory / f"{identifier}.py")
            .read_bytes()
            .decode("utf-8")
        }
    msg = f"Unknown custom action operation {operation}"
    raise ValueError(msg)


async def _csv(
    runtime: CustomActionRuntime, operation: str, params: dict[str, Any]
) -> object:
    if operation == "csv.list":
        return await _storage(runtime.csv.list)
    if operation == "csv.open":
        return await _storage(runtime.csv.open, params["name"])
    if operation == "csv.read":
        if type(params["offset"]) is not int:
            msg = "offset must be an integer byte position"
            raise ValueError(msg)
        return await _storage(runtime.csv.read, params["token"], params["offset"])
    if operation == "csv.close":
        return await _storage(runtime.csv.close, params["token"])
    if operation == "csv.delete":
        return await _storage(runtime.csv.delete, params["name"])
    msg = f"Unknown CSV operation {operation}"
    raise ValueError(msg)


async def _storage(function: Callable[..., object], *args: object) -> object:
    """Finish in-flight file operations before connection cleanup removes snapshots."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
