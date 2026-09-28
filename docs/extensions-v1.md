# Manafish Python SDK v1

Create one UTF-8 `.py` file using `Context`, `Script`, `Trigger`, and `Widget`
from `manafish_sdk`. Declare one `Script` at module level. Register readings
and functions through it; the SDK generates the app's catalogue automatically.

```python
from manafish_sdk import Context, Script, Trigger, Widget

script = Script("depth_monitor", name="Depth monitor")
depth = script.reading("depth", float, unit="m", widget=Widget.TEXT)

@script.action(name="Read depth", modes=(Trigger.ONCE, Trigger.HOLD, Trigger.TOGGLE))
async def sample(ctx: Context) -> None:
    if not ctx.rov.system_health.pressure_sensor_healthy:
        await depth.publish(None)
        raise RuntimeError("Pressure sensor is unavailable")
    await depth.publish(ctx.rov.pressure.depth)
```

The script ID is its stable namespace: lowercase letters, digits, underscores;
starts with a letter, at most 48 characters. `rov` is reserved for built-ins.
Each reading ID and decorated function name identifies a capability, such as
`depth_monitor.depth` and `depth_monitor.sample`. Keep these IDs stable when
updating so layouts and bindings survive. When renaming a function, retain its
old ID with `@script.action(identifier="old_name")`.

Saving and validation prepare the module off the firmware event loop. The prepared
module is reused for saving and first enable while cached. Reloading creates a
fresh module. Imports have a 10-second timeout and only one can run at a time. A
timed-out import must finish before another starts; Python threads cannot be
forcibly stopped. A bounded cache releases unused prepared modules. Module
initialization must only declare configuration, readings, and functions. Open
hardware, write files, and start work inside registered functions. Validation
does not invoke actions or background tasks and cannot prove hardware behavior.
Scripts are trusted Python running in the firmware process. Sources are limited
to 256 KiB; installation transfers the exact source and leaves new scripts disabled.

## Readings and widgets

`script.reading("id", bool)` returns a `Reading[bool]`. Other supported Python
types are `int`, `float`, `str`, `list[float]`, and NumPy arrays such as
`NDArray[np.float64]` (import `NDArray` from `numpy.typing`). Numeric arrays
retain their Python type until serialization into the shared stream. Optional arguments are `name`,
`unit`, `widget`, and `stale_after` (seconds). Widget suggestions are `Widget.TEXT`, `Widget.STATUS`,
`Widget.WARNING`, `Widget.PING`, and `Widget.BAR`.

Call `await wet.publish(True)` on the reading object. The value must match its
Python type; numbers must be finite, and numeric lists support up to 4096 items.
Use `None` to mark a reading unavailable. Repeated identical values produce new
events, so a ping light can flash on each publication. Publishing does not create
a widget automatically: operators choose and position it in Appearance.

Widgets show the age of their last reading. For continuous readings, opt into a
freshness deadline, for example `script.reading("depth", float, stale_after=2.0)`.
Publish every measurement, including unchanged values, to renew freshness. A
missed deadline displays **Stale**, not an inactive sensor light. Leave the timeout
unset for manually sampled values; their age remains visible. No sample yet,
explicitly unavailable values, and failed scripts have distinct states.
Source age travels with updates and catalogue snapshots, and the app advances it
using a monotonic clock so different PC/ROV clock settings do not affect it.

## Live typed ROV state

`ctx.rov` is the actual firmware `RovState`, with its original nested Python and
NumPy types. `RovState` is also exported from `manafish_sdk` for annotations.
Access data and methods directly:

```python
depth = ctx.rov.pressure.depth  # float
water_temperature = ctx.rov.pressure.temperature  # float
roll = ctx.rov.regulator.roll  # float
depth_hold = ctx.rov.system_status.depth_hold  # bool
acceleration = ctx.rov.imu.acceleration  # original numpy array
pending_depth = ctx.rov.regulator.pending_desired_depth  # float | None
await ctx.rov.set_desired_depth(12.0)
await ctx.rov.set_desired_attitude((0.0, 0.0, 0.0, 1.0))  # XYZW
```

Check `ctx.rov.system_health` before relying on sensor values. Defaults do not
prove a sensor is installed or healthy. State stays live without an app connection.
Firmware models and helpers can be imported normally; definitions live in
`rov_firmware/rov_state.py` and `rov_firmware/models/`. Capability IDs on the
app wire are not Python attribute paths.

## Actions and background work

`@script.action()` registers an async function taking `ctx: Context`. Its default
trigger is `Trigger.ONCE`. Add `Trigger.HOLD` or `Trigger.TOGGLE` to `modes` when
repetition makes sense. `mode` selects the initial trigger and `interval_ms` its
delay (default 250, range 50–3600000). Operators adjust these in Custom actions;
bindings appear with ordinary Keyboard, Controller, and Appearance controls.

Implement one operation per invocation. The firmware schedules repeats after
completion, without overlap. Hold stops on release, toggle on a second press or
Stop. All operator loops stop on disconnect and never resume automatically.
For API actions taking a value, annotate the second argument, for example
`async def set_target(ctx: Context, value: float) -> None`. Its input type is
inferred; actions requiring an input are not offered as simple button bindings.

For continuous sensing, use `@script.background()` above an async function taking
`ctx: Context`. Use `await asyncio.sleep(seconds)` between samples. Add
`continue_on_disconnect=True` only for background work that should run without
an operator. Enabled backgrounds with this opt-in start unattended after a ROV
restart; other enabled scripts start when an operator connects. Keep actuator
activation in explicitly invoked actions.

Use normal module variables for typed state shared across calls. Each loaded
script has its own module; state resets on reload, update, disable/enable, or
restart. Use a Pydantic model for structured state; the SDK has no untyped state
dictionary. Module state is not persistent storage. Coordinate concurrent access if an action and background
use the same hardware or state.

Yield in loops, release resources in `try/finally`, and let `asyncio.CancelledError`
propagate. Blocking work stalls the firmware event loop. Use `asyncio.to_thread`
for blocking I/O and wait for it during cleanup; threads cannot be forcibly
cancelled. Avoid detached tasks or threads. A task that refuses cancellation
prevents replacement until it finishes. Installed libraries are available;
installing additional dependencies is outside V1.


```python
from pydantic import BaseModel

class SensorState(BaseModel):
    last_wet: bool | None = None

state = SensorState()
# In an action: state.last_wet = water_detected
```

## Editor completion and checks

The desktop editor runs a bundled ty language server locally for member completion,
argument signatures, hover documentation, and inline type errors. It never executes
the draft or imports it on the ROV. Saving and enabling remain separate runtime
operations and may execute module initialization.

Connect once to fetch the firmware's actual SDK, RovState, model, and installed
runtime-library sources. The app caches these definitions for offline editing and
checks their content revision when connecting again. A status message distinguishes
cached definitions from the connected ROV's current definitions. Before the first
successful sync, standard Python completion is available but SDK types are missing.
No Python installation is required on the PC. Static analysis cannot prove that
hardware exists or that an operation is safe for the connected equipment.

## CSV logging and diagnostics

`await ctx.log_csv([value1, value2], "readings.csv")` appends one row. A
one-dimensional NumPy array also works. Use a plain `.csv` filename without
directories. Keep the same column count for every row in a file. Write a header
only once, and include timestamps explicitly when useful. Call this from an
action for operator-controlled logging or an opted-in background for unattended
logging.

Sources, settings, and CSVs persist under `~/.local/share/manafish/` on the ROV.
CSV logging settings list, download, and delete recordings. Downloads are
snapshots, so recording can continue during transfer. File limits are 64 MiB each
and 256 MiB total. A running logger can recreate a file after deletion.

Use `await ctx.notify("Water detected", level=NotificationLevel.WARNING)` for a
notification. Import `NotificationLevel` from `manafish_sdk`; levels are `INFO`
(the default), `SUCCESS`, `WARNING`, and `ERROR`. Optional `description` is plain
text. A `key="status"` replaces the script's previous notification with that key
rather than adding another; keys are scoped to the script. For repeated sensor
reads, publish every sample but notify on the first result and subsequent state
changes. The bundled water sensor follows this pattern.

Use `await ctx.log("A useful diagnostic message")` for the Debug page. Unhandled
errors identify the script and stop its work. Report missing hardware and invalid
readings accurately; do not substitute a simulated value for a failed sensor.

## Water sensor example

For the original active-high sensor, connect S to Pi pin 11 (GPIO17), + to pin 1
(3V3), and - to pin 6 (GND). Copy `examples/extensions/water_sensor.py` into a new
custom action, save it, then enable it. Add **Water detected** from Appearance
if you want its warning widget over the video.

Enabling starts continuous monitoring immediately. Each read is followed by a
250 ms delay; change `SAMPLE_INTERVAL_SECONDS` to adjust it. Every read refreshes
the widget, with a notification on the first result and each wet/dry change.
After two seconds without a new reading, the widget marks its value stale.
Bind **Toggle monitoring** to an action widget or a Keyboard/Controller button
for temporary pause/resume. Each press changes state once; it uses the default
tap-once trigger, not the repeating toggle trigger. While paused, no GPIO reads
run and the sensor reading is unavailable. Resuming samples again within 250 ms
and reports the first result. Pauses reset when the script reloads, including
after an app disconnect or ROV restart. Disable the custom action in settings
if monitoring should stay off across disconnects and restarts. Notifications are live, not a history of disconnected events.
A GPIO error reports the failure and stops monitoring; fix the wiring or driver
and disable/re-enable the script to retry. A disconnected sensor wire may read
as dry; a digital GPIO input cannot detect whether the sensor is physically present.

## Agent output

Return one complete Python file using this SDK and a short testing checklist.
Keep configuration easy to find. Explain required wiring and installed libraries;
do not invent hardware pin assignments. Use the existing widgets and firmware
APIs. No separate manifest dictionary or firmware source changes are needed.

## Wire contract and compatibility

This is a coordinated desktop app/firmware V1 change. The new desktop app
requires the capability protocol. Upgrade the firmware first, then the app;
do not operate with an old app and this firmware. MCU control protocol and
hardware safety handlers are unchanged. Configuration and maintenance messages
retain their existing transport. Telemetry/status and custom value updates
use one capability stream.

Requests: `{"type":"capabilityRequest","payload":{"version":1,
"requestId":"unique","operation":"catalog.get","params":{}}}`.
Responses: `capabilityResponse` with version, requestId, ok, result or
`error:{code,message}`. `capabilityCatalog` contains version, readings, actions,
extensions and samples. `capabilitySamples` contains version and samples.
Each sample has id, value, sequence, timestamp (Unix milliseconds), and ageMs
(elapsed monotonic source age at serialization). Readings may declare staleAfterMs.
Sequence increases even for identical custom publications. A catalogue includes
current values so reconnection does not require a fresh sensor event.

Operations: `catalog.get`; `action.invoke` (id, phase press/release/stop, value);
`action.configure` (id, mode, intervalMs); `extension.list/validate/install/remove/
source/enable`; `csv.list/open/read/close/delete`. CSV list returns an array of
{name,rows,columns,size}; open returns {token,size}; read accepts token and byte
offset and returns {data (base64),nextOffset,eof}, up to 64 KiB per chunk.
Close releases the snapshot; disconnect releases all outstanding snapshots.

SDK analysis operations: `sdk.describe` returns `{revision,size}` for a gzip JSON
map of relative Python paths to their exact sources; `sdk.read` accepts revision
and integer byte offset and returns `{data,nextOffset,eof}` in 64 KiB chunks.
The revision is the compressed archive's SHA-256. Sources are collected off-loop
and cached for the firmware process lifetime. Only SDK/firmware code and installed
runtime dependency definitions are included, never operator scripts or settings.
The desktop limits compressed archives to 16 MiB and expanded sources to 64 MiB.
