"""ROV-owned extension registry, lifecycle and unified samples/actions."""

import asyncio
from collections import deque
from contextlib import suppress
import json
from pathlib import Path
import re
import time
from typing import Any

from pydantic import JsonValue, TypeAdapter

from ..log import log_error, log_warn
from ..rov_state import RovState
from . import builtins
from .csv_store import CsvStore
from .models import (
    Action,
    ExtensionInfo,
    ExtensionPreferences,
    Manifest,
    Reading,
    Sample,
)
from .preparation import ScriptPreparation
from .runner import ExtensionRunner
from .sdk import Context
from .values import normalize_value


STATUS_PERIOD = 0.5
_SETTINGS = TypeAdapter(dict[str, ExtensionPreferences])


class ExtensionRuntime:
    """Maintain one capability namespace for built-ins and trusted extensions."""

    def __init__(self, state: RovState, directory: Path) -> None:
        """Initialize persistent source/config storage, without executing scripts."""
        self.state = state
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.csv = CsvStore(directory.parent / "csv")
        self.manifests: dict[str, Manifest] = {}
        self.extensions: dict[str, ExtensionInfo] = {}
        self.readings = {item.id: item for item in builtins.readings()}
        self.actions = {item.id: item for item in builtins.actions()}
        self.samples: dict[str, Sample] = {}
        self.events: deque[Sample] = deque(maxlen=4096)
        self.runners: dict[str, ExtensionRunner] = {}
        self.running: set[str] = set()
        self.sequence = 0
        self._last_status_sample = float("-inf")
        self.catalog_changed = True
        self._lock = asyncio.Lock()
        self._fault_tasks: set[asyncio.Task[None]] = set()
        self.settings: dict[str, Any] = self._load_settings()
        self._preparation = ScriptPreparation()
        self._initialized = False
        self.refresh_builtins()

    def _load_settings(self) -> dict[str, Any]:
        path = self.directory / "settings.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            preferences = _SETTINGS.validate_python(data)
            return {key: value.model_dump() for key, value in preferences.items()}
        except (ValueError, OSError) as error:
            log_error(f"Extension settings could not be loaded: {error}")
            return {}

    def _save(self) -> None:
        path = self.directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.settings, indent=2))
        temporary.replace(path)

    async def _load_sources(self) -> None:
        for path in sorted(self.directory.glob("*.py")):
            try:
                if path.stem in self.manifests:
                    continue
                loaded = await self._preparation.prepare(
                    path.read_bytes().decode("utf-8")
                )
                manifest = loaded.definition
                if path.stem != manifest.id:
                    msg = "Installed filename differs from script ID"
                    raise ValueError(msg)
                self._register(manifest)
            except Exception as error:
                log_error(f"Cannot load extension {path.name}: {error}")
                if (
                    path.stem == "rov"
                    or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", path.stem) is None
                ):
                    continue
                self.extensions[path.stem] = ExtensionInfo(
                    id=path.stem,
                    name=path.stem,
                    description="",
                    status="error",
                    error=f"Cannot load script: {error}",
                )

    @staticmethod
    def qualify(manifest: Manifest) -> tuple[list[Reading], list[Action]]:
        """Expand local source identifiers into globally stable capability IDs."""
        readings = [
            item.model_copy(update={"id": f"{manifest.id}.{item.id}"})
            for item in manifest.readings
        ]
        actions = [
            item.model_copy(update={"id": f"{manifest.id}.{item.id}"})
            for item in manifest.actions
        ]
        for action in actions:
            readings.append(
                Reading(
                    id=f"{action.id}.running",
                    name=f"{action.name} running",
                    value_type="boolean",
                    extension_id=manifest.id,
                )
            )
        return readings, actions

    def _register(self, manifest: Manifest) -> None:
        self.manifests[manifest.id] = manifest
        settings = self.settings.get(manifest.id, {})
        self.extensions[manifest.id] = ExtensionInfo(
            id=manifest.id,
            name=manifest.name,
            description=manifest.description,
            enabled=bool(settings.get("enabled", False)),
        )
        readings, actions = self.qualify(manifest)
        self.readings.update({item.id: item for item in readings})
        for declaration in actions:
            action = declaration
            configured = settings.get("actions", {}).get(action.id)
            if configured:
                try:
                    action = Action.model_validate(
                        {**action.model_dump(), **configured}
                    )
                except ValueError as error:
                    log_warn(
                        f"Ignoring incompatible action configuration {action.id}: {error}"
                    )
            self.actions[action.id] = action
            self.publish(f"{action.id}.running", False)
        self.catalog_changed = True

    def publish(self, identifier: str, value: object) -> None:
        """Validate every sample and retain event identity for ping/log widgets."""
        reading = self.readings.get(identifier)
        if reading is None:
            msg = f"Reading {identifier} is not declared"
            raise ValueError(msg)
        # None explicitly means unavailable, including disconnected sensors.
        normalized = (
            None if value is None else normalize_value(value, reading.value_type)
        )
        self.sequence += 1
        sample = Sample(
            id=identifier,
            value=normalized,
            sequence=self.sequence,
            timestamp=time.time() * 1000,
        )
        self.samples[identifier] = sample
        self.events.append(sample)

    def refresh_builtins(self) -> None:
        """Sample built-in values into the same stream as extension publications."""
        now = time.monotonic()
        include_status = now - self._last_status_sample >= STATUS_PERIOD
        if include_status:
            self._last_status_sample = now
        for identifier, value in builtins.values(
            self.state, include_status=include_status
        ).items():
            previous = self.samples.get(identifier)
            if previous is None or previous.value != value:
                try:
                    self.publish(identifier, value)
                except ValueError as error:
                    if previous is None or previous.value is not None:
                        log_warn(f"Invalid built-in reading {identifier}: {error}")
                        self.publish(identifier, None)

    def catalog(self) -> dict[str, Any]:
        """Return definitions and current values, including on reconnect."""
        return {
            "version": 1,
            "readings": [
                item.model_dump(by_alias=True) for item in self.readings.values()
            ],
            "actions": [
                item.model_dump(by_alias=True) for item in self.actions.values()
            ],
            "extensions": [
                item.model_dump(by_alias=True) for item in self.extensions.values()
            ],
            "samples": [
                item.model_dump(by_alias=True) for item in self.samples.values()
            ],
        }

    async def initialize(self) -> None:
        """Start explicitly enabled sensor backgrounds; never replay actions."""
        if not self._initialized:
            await self._load_sources()
            self._initialized = True
        for identifier, info in self.extensions.items():
            manifest = self.manifests.get(identifier)
            if (
                manifest is not None
                and info.enabled
                and manifest.background
                and manifest.continue_on_disconnect
            ):
                await self._start(identifier)

    def _context(self, identifier: str) -> Context:
        def publish(local_id: str, value: object) -> None:
            declared = {reading.id for reading in self.manifests[identifier].readings}
            if local_id not in declared:
                msg = "Only declared local readings can be published"
                raise ValueError(msg)
            self.publish(f"{identifier}.{local_id}", value)

        return Context(self.state, publish, self.csv, identifier)

    async def _start(self, identifier: str) -> None:
        def on_running(local_id: str, running: bool) -> None:
            if self.runners.get(identifier) is not runner:
                return
            action_id = f"{identifier}.{local_id}"
            if running:
                self.running.add(action_id)
            else:
                self.running.discard(action_id)
            self.publish(f"{action_id}.running", running)

        def on_error(reason: str) -> None:
            task = asyncio.create_task(self._handle_failure(identifier, runner, reason))
            self._fault_tasks.add(task)
            task.add_done_callback(self._fault_tasks.discard)

        info = self.extensions[identifier]
        try:
            path = self.directory / f"{identifier}.py"
            loaded = await self._preparation.take(path.read_bytes().decode("utf-8"))
            if loaded.definition != self.manifests[identifier]:
                loaded.close()
                msg = "Custom action declarations changed; save the script again"
                raise ValueError(msg)
            loaded.module.__file__ = str(path)
            runner = ExtensionRunner(
                loaded, self._context(identifier), on_running, on_error
            )
            self.runners[identifier] = runner
            await runner.start()
            info.status = "running"
            info.error = None
        except Exception as error:
            self.runners.pop(identifier, None)
            info.status = "error"
            info.error = str(error)
            log_error(f"Extension {identifier} failed to start: {error}")
        self.catalog_changed = True

    async def _stop(self, identifier: str) -> None:
        runner = self.runners.get(identifier)
        if runner is not None:
            try:
                await runner.stop()
            except TimeoutError as error:
                self.extensions[identifier].status = "error"
                self.extensions[identifier].error = str(error)
                self.catalog_changed = True
                log_error(f"Extension {identifier}: {error}")
                raise
            self.runners.pop(identifier, None)
        for action_id in list(self.running):
            if action_id.startswith(f"{identifier}."):
                self.running.discard(action_id)
                self.publish(f"{action_id}.running", False)
        for reading in self.readings.values():
            if (
                reading.extension_id == identifier
                and not reading.id.endswith(".running")
                and reading.id in self.samples
            ):
                self.publish(reading.id, None)
        self.extensions[identifier].status = "stopped"
        self.catalog_changed = True

    async def enable(self, identifier: str, enabled: bool) -> dict[str, Any]:
        """Persist explicit enablement and reconcile task state."""
        async with self._lock:
            info = self.extensions[identifier]
            if enabled and identifier not in self.manifests:
                msg = "Edit and save the custom action to fix its declarations before enabling it"
                raise ValueError(msg)
            await self._stop(identifier)
            self.settings.setdefault(identifier, {})["enabled"] = enabled
            self._save()
            info.enabled = enabled
            if enabled:
                await self._start(identifier)
            return info.model_dump(by_alias=True)

    async def validate(self, source: str) -> dict[str, Any]:
        """Discover declarations without invoking actions or background tasks."""
        loaded = await self._preparation.prepare(source)
        manifest = loaded.definition
        readings, actions = self.qualify(manifest)
        return {
            "manifest": manifest.model_dump(by_alias=True),
            "readings": [item.model_dump(by_alias=True) for item in readings],
            "actions": [item.model_dump(by_alias=True) for item in actions],
            "warnings": [
                "Validation imports trusted Python declarations. It does not invoke actions or prove hardware correctness."
            ],
        }

    async def install(self, source: str) -> dict[str, Any]:
        """Atomically install exact source bytes, retaining stable preferences."""
        loaded = await self._preparation.prepare(source)
        manifest = loaded.definition
        async with self._lock:
            path = self.directory / f"{manifest.id}.py"
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(source.encode("utf-8"))
            if manifest.id in self.extensions:
                await self._stop(manifest.id)
            temporary.replace(path)
            if manifest.id in self.extensions:
                self._unregister(manifest.id)
            self._register(manifest)
            if self.extensions[manifest.id].enabled:
                await self._start(manifest.id)
            return self.extensions[manifest.id].model_dump(by_alias=True)

    def _unregister(self, identifier: str) -> None:
        for collection in (self.readings, self.actions, self.samples):
            for key in list(collection):
                if key.startswith(f"{identifier}."):
                    del collection[key]
        self.manifests.pop(identifier, None)
        self.extensions.pop(identifier, None)
        self.events = deque(
            (
                sample
                for sample in self.events
                if not sample.id.startswith(f"{identifier}.")
            ),
            maxlen=4096,
        )
        self.catalog_changed = True

    async def remove(self, identifier: str) -> None:
        """Stop an installed extension before removing its source and preferences."""
        async with self._lock:
            if identifier not in self.extensions:
                raise KeyError(identifier)
            await self._stop(identifier)
            (self.directory / f"{identifier}.py").unlink()
            self._unregister(identifier)
            self.settings.pop(identifier, None)
            self._save()

    async def configure(
        self, identifier: str, mode: str, interval_ms: int
    ) -> dict[str, Any]:
        """Serialize trigger edits with extension lifecycle mutations."""
        async with self._lock:
            return await self._configure(identifier, mode, interval_ms)

    async def _configure(
        self, identifier: str, mode: str, interval_ms: int
    ) -> dict[str, Any]:
        """Validate and persist supported trigger modes on the ROV."""
        action = Action.model_validate(
            {
                **self.actions[identifier].model_dump(),
                "mode": mode,
                "interval_ms": interval_ms,
            }
        )
        if action.extension_id is None:
            msg = "Built-in trigger behavior is fixed"
            raise ValueError(msg)
        await self._invoke(identifier, "stop")
        preferences = self.settings.setdefault(action.extension_id, {}).setdefault(
            "actions", {}
        )
        preferences[identifier] = {
            "mode": action.mode,
            "interval_ms": action.interval_ms,
        }
        self._save()
        self.actions[identifier] = action
        self.catalog_changed = True
        return action.model_dump(by_alias=True)

    async def invoke(
        self,
        identifier: str,
        phase: str = "press",
        value: JsonValue = None,
        *,
        once: bool = False,
    ) -> None:
        """Serialize extension invocation without blocking built-in vehicle controls."""
        if identifier.startswith("rov."):
            await self._invoke(identifier, phase, value, once=once)
            return
        async with self._lock:
            await self._invoke(identifier, phase, value, once=once)

    async def _invoke(
        self,
        identifier: str,
        phase: str = "press",
        value: JsonValue = None,
        *,
        once: bool = False,
    ) -> None:
        """Use shared invocation semantics and never queue overlapping executions."""
        action = self.actions.get(identifier)
        if action is None:
            msg = f"Action {identifier} is not available"
            raise ValueError(msg)
        if phase not in ("press", "release", "stop"):
            msg = "Unknown action phase"
            raise ValueError(msg)
        if action.extension_id is None:
            if phase == "press":
                await builtins.invoke(self.state, identifier, value)
            return
        runner = self.runners.get(action.extension_id)
        stopping = phase == "stop" or (phase == "release" and action.mode == "hold")
        stopping = stopping or (
            phase == "press"
            and action.mode == "toggle"
            and identifier in self.running
            and not once
        )
        if stopping:
            await self._cancel_action(action, runner)
            return
        if phase != "press" or identifier in self.running:
            return
        if runner is None or self.extensions[action.extension_id].status != "running":
            msg = "Enable the extension before invoking its actions"
            raise ValueError(msg)
        if action.input_type != "none":
            value = normalize_value(value, action.input_type)
        self.running.add(identifier)
        try:
            runner.invoke(
                identifier.split(".", 1)[1],
                value,
                "once" if once else action.mode,
                action.interval_ms,
            )
        except Exception as error:
            await self._failed(
                action.extension_id, f"Action invocation failed: {error}"
            )
            raise

    async def _cancel_action(
        self, action: Action, runner: ExtensionRunner | None
    ) -> None:
        if runner is not None and action.extension_id is not None:
            try:
                await runner.cancel(action.id.split(".", 1)[1])
            except Exception as error:
                await self._failed(
                    action.extension_id, f"Action cancellation failed: {error}"
                )
                raise
        self.running.discard(action.id)
        self.publish(f"{action.id}.running", False)

    async def _handle_failure(
        self, identifier: str, runner: ExtensionRunner, reason: str
    ) -> None:
        async with self._lock:
            if self.runners.get(identifier) is runner:
                # Retain ownership of tasks that refused cancellation.
                with suppress(TimeoutError):
                    await self._failed(identifier, reason)

    async def _failed(self, identifier: str, reason: str) -> None:
        await self._stop(identifier)
        self.extensions[identifier].status = "error"
        self.extensions[identifier].error = reason
        log_error(f"Extension {identifier}: {reason}")

    async def disconnected(self) -> None:
        """Cancel operator tasks before restarting opted-in background work."""
        async with self._lock:
            for identifier in list(self.runners):
                try:
                    await self._stop(identifier)
                except TimeoutError:
                    continue
                manifest = self.manifests[identifier]
                if (
                    self.extensions[identifier].enabled
                    and manifest.background
                    and manifest.continue_on_disconnect
                ):
                    await self._start(identifier)
            await asyncio.to_thread(self.csv.close_all)

    async def connected(self) -> None:
        """Resume enabled extension availability without replaying operator actions."""
        for identifier, info in self.extensions.items():
            if (
                info.enabled
                and info.status != "error"
                and identifier not in self.runners
            ):
                await self._start(identifier)

    async def shutdown(self) -> None:
        """Stop extension tasks and release temporary download snapshots."""
        async with self._lock:
            for identifier in list(self.runners):
                with suppress(TimeoutError):
                    await self._stop(identifier)
        self._preparation.close()
        await asyncio.gather(*self._fault_tasks, return_exceptions=True)
        await asyncio.to_thread(self.csv.close_all)
