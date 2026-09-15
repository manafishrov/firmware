# Pico SPI attitude migration handoff

Task: `pico-spi-attitude-500hz`. This is the cross-repository coordination record.
Software implementation and portable checks are complete. **Hardware acceptance
is blocked at physical IMU identification.** The verified migration image is
installed on the original RP2040, but BMI270 chip ID reads `0x00`, not `0x24`.
The first neutral smoke failed; actual AHRS/PID counts were zero. No functioning
500 Hz loop, headroom estimate, or complete migration acceptance is claimed.

The original Pi service is stopped and the Pico was explicitly left in sticky
neutral maintenance after the failure. The next step is to confirm the exact
SparkFun board/photo and wiring, not to deploy or publish. On the standard
full-size breakout, primary MISO is **ADR/POCI, not OSDO**; GP10 goes to SCL/SCK,
GP11 to SDA/MOSI, GP12 to ADR/MISO, and GP13 to CS, with 3V3 and common ground.
SparkFun requires an open address jumper for SPI, but its 100k bias does not by
itself prove the cause. Verify the board before modifying it; disconnect power
before physical changes.

Coordinator-owned evidence (do not overwrite from the Python workstream):

- [Hardware backup, current deployment state and rollback](docs/pico-control-validation/BACKUP.md)
- [Independent app gate results](docs/pico-control-validation/APP.md)
- [Pi firmware gates and focused re-review](docs/pico-control-validation/FIRMWARE.md)
- [C/Python oracle and sensor-conversion provenance](docs/pico-control-validation/MATH.md)
- [Actual hardware results, blocker and safe state](docs/pico-control-validation/HARDWARE.md)

Implementation commits on `feat/pico-spi-attitude-500hz`:

- app: `6a16ff5b3a824714b243e82cd778136f52bdacf5`
- firmware: `0e8903f` (subsequent documentation commits record hardware results)
- mcu-firmware: `b817d1d3da143bbb1d56ce4a86ff0a15e5ae1f3c`

Installed MCU identity: `pico-control-dev:b817d1d3da14`. Installed UF2 SHA256:
`21f22a2eeb34bba47699468aadd3d0d50d284711db1f7438f36ef2749f683339`.
Do not use the earlier uncorrected MCU commit `7f152f8` or identify an image
merely by that prefix.

## Repositories, compatibility and release gate

| Repository | Baseline | Task branch | Responsibility |
| --- | --- | --- | --- |
| firmware | `b62cbeeec7448104a02cc7b8d22c5558b2310414` | `feat/pico-spi-attitude-500hz` | Pi orchestration, transactions, frozen oracle, this handoff |
| app | `08be354` | `feat/pico-spi-attitude-500hz` | Config rejection envelope and 12-second mutation wait |
| mcu-firmware | `47c503e` | `feat/pico-spi-attitude-500hz` | SPI, pure controller, multicore runtime, output safety and protocol |

Install the new app first. Old apps can mistake a rejected canonical Config for
success because they do not understand `payload.error`. Pair the new Pi and Pico
afterward. The new Pi holds an incompatible Pico neutral; it has no Pi-side
attitude fallback.

**Release gate:** current bundled MCU v1.0.3 artifacts lack the new protocol.
Normal bundled-version reconciliation can also replace a development Pico with
that incompatible image. Before publishing, a separately authorized compatible
MCU release, both Pico/Pico 2 flake artifact pins, and the Pi image must be paired.
No release, version bump, pin bump, push or PR is authorized by this task.

The bench-only exception is `MANAFISH_PICO_CONTROL_DEVELOPMENT=1`, and only after
verified compatible capabilities with an identity prefixed `pico-control-dev:`.
An arbitrary version or feature bit alone cannot bypass release defaults. Remove
the environment override when rolling back or deploying the eventual release.

The authoritative wire contract is `docs/PICO_CONTROL_PROTOCOL.md` in the MCU
repository. Python explicitly packs that contract in
`src/rov_firmware/pico_protocol.py`; this document does not fork its layout.

## Ownership and rates

- Pi smooths direction at 60 Hz. The original per-axis slew step remains
  `1 / (60 * smoothing_factor)`; factors at or below `1/60` bypass smoothing.
- Pi reads MS5837 pressure over I2C at 15 Hz. Depth derivative remains
  `(new_depth - old_depth) / measured_dt`, filtered with EMA coefficient
  `exp(-dt / 0.03)`. Fluid density follows the existing fresh/saltwater setting.
  Every new sample is sent, including unchanged values. A local monotonic sample
  timestamp prevents reconnect from relabelling an old pressure value as fresh.
- Pico core 1 owns BMI270 SPI, Mahony, attitude PID and allocation at 500 Hz.
  SPI1 uses GP10 SCK, GP11 MOSI, GP12 MISO and GP13 CS. Core 0 exclusively owns
  USB, physical outputs, maintenance and safety arbitration.
- Desired attitude, desired depth and depth PID advance once per accepted
  60 Hz direction command. Commands remain ordered; a retry cannot advance a
  target twice. Source dt keeps the legacy clamp `[1/120, 1/6]`, fallback `1/60`.
  AHRS/attitude dt instead uses `[0.001, 0.02]`, fallback `0.002`, for 500 Hz.
- Nullspace avoidance solves at 500 Hz, but its `0.001` activation decay occurs
  once per 60 Hz command. It must not decay 8.3 times faster after migration.
- Actual/desired attitude and raw IMU project at 60 Hz. Device completion counts
  and durations cover real 5-second windows. A controller execution counter
  does not prove the per-motor waveform or ESC reception rate.

## Exact baseline semantics

The runnable original sources are frozen in `tests/reference/*_b62cbee.txt`.
`tests/test_pico_differential.py` checks their hashes and executes their methods
against the actual C controller, rather than generating expected values from C.

### IMU and Mahony

The original Pi BMI270 setup used performance mode, ±2 g, ±1000 deg/s,
200 Hz accelerometer/gyro ODR, normal bandwidth, FIFO headers disabled,
streaming enabled, accelerometer filter performance, and gyro noise/filter
performance enabled. Migration deliberately changes acquisition to SPI and
800 Hz ODR to support fresh samples at 500 Hz. Physical sample streams are
therefore not claimed bit-identical to the old sensor schedule.

Signed little-endian acceleration/gyro samples come from registers `0x0c..0x17`.
Acceleration is `raw / 32768 * acc_range`, and gyro is
`pi/180 * raw / 32768 * gyr_range`. Both become float32 and multiply
componentwise by `[+1, -1, -1]`. Preserve that sign flip; do not substitute a
generic ENU/NED axis swap. Temperature is signed register `0x22`, multiplied
by `0.001952594`, then increased by 23.

The coordinator verified the actual installed Pi BMI270 namespace package
without sensor I/O. It is byte-identical to local version 0.4.3:

- `GRAVITY = 9.81288`; `acc_range = 2 * GRAVITY`. Acceleration is **m/s²**.
- Gyroscope output is **rad/s**. The SPI driver matches these units/scales.
- `definitions.py` SHA256:
  `5df117580a084bd102f533f4c14a93fbc5e95085dc5b423e656e87425857fded`.
- `BMI270.py` SHA256:
  `86f0685d047b5cb94794aab1354f38e75e846ba360642cd0c564776df82eb59a`.

Quaternion convention is SciPy XYZW, body-to-world, with intrinsic ZYX Euler
angles for display. Mahony starts at identity with zero integral. Kp is 1.5 and
Ki is 0.05. Estimated body-up is `inverse(q) * [0, 0, -1]`; error is
`cross(normalized_accel, estimated_up)`. Its integral adds `error * Ki * dt`
without a windup clip. Corrected angular velocity is gyro + Kp × error + integral.
Integrate using the rotation-vector exponential,
`q = q * Exp(omega * dt)`, then normalize. Do not substitute Euler quaternion
integration.

A nonfinite acceleration norm, or norm below `0.001`, uses gyro-only integration
without the accumulated Mahony correction. Any gyro component above
1080 deg/s zeros the entire AHRS gyro sample. PID deliberately retains the
original gyro copied before rejection. Preserve this oracle quirk separately
from hardware stale/nonfinite-sample safety.

### Desired attitude and PID

Direction order is surge, sway, heave, pitch, yaw, roll, action1, action2.
Normal desired-attitude integration performs, in order:

1. World-Z yaw pre-multiplication.
2. Intrinsic ZYX extraction, pitch addition, clipping to ±80 degrees and rebuild.
3. Body-X roll post-multiplication.

FPV mode instead post-multiplies one rotation-vector increment
`[roll, pitch, yaw]` without the Euler pitch clip. Rates are degrees/second.
Defaults for roll, pitch and yaw are Kp 6, Ki 2, Kd 0.6, rate 120. Depth defaults
are Kp 2, Ki 0, Kd 0.5, rate 0.5 m/s. FPV defaults off. Thruster/action/regulator
limits default to 30/50/30 percent; coefficients to 1/1/1; pin mapping to
identity; spins to +1; nullspace list to empty.

PID error is the shortest rotvec of `inverse(actual) * desired`, in radians.
Nonfinite error becomes zero. Attitude integral accumulates only when the norm
of pilot pitch/yaw/roll is **strictly below 0.2**; otherwise it freezes. Each
integral component clips to ±100 degrees converted to radians. Derivative is
negative body gyro rate, not finite-differenced error. Apply roll/x, pitch/y and
yaw/z gains, divide outputs by 10, and store them in pitch/yaw/roll slots.
Output saturation does not introduce a new antiwindup law.

A stabilization rising edge levels desired pitch/roll, preserves actual yaw,
clears attitude integral, and then applies that command's increments. Falling
edges retain the internal target/integral but zero displayed desired pitch/roll;
yaw display remains. Repeated set-enabled is not a rising edge.

### Depth and movement coupling

Depth enable selects a pending explicit target or current pressure depth and
clears depth integral. Disable clears the pending target. Explicit setters reject
nonfinite values and clamp targets to at least zero. Integrated heave targets
are **not clamped**: `target += heave * depth_rate * source_dt` can go negative.

Depth error is target minus current. Its integral adds
`error * dt * clip(1 - abs(heave), 0, 1)` and clips to ±3. PID is
`kp * error + ki * integral - kd * filtered_depth_change`, without division by 10.

With depth hold enabled, remove actual yaw but retain pitch/roll. Transform both
world-depth actuation and pilot surge/sway into the body frame, and zero pilot
heave. Preserve the coefficient ratios surge/heave, sway/heave, heave/surge and
heave/sway. A zero denominator gives a zero ratio. The old math substitutes 1 for
nonfinite coefficients; the new wire rejects nonfinite settings. Do not replace
this operation with an unweighted quaternion vector transform. Without depth
hold, pilot translation is not transformed.

### Allocation, limits, nullspace and output

1. Retain pre-limit combined user/regulator direction for the work indicator.
   Work is average absolute allocated thrust, individually clipped, multiplied
   by 100 and truncated across eight motors. Exclude nullspace correction.
2. Scale user axes 0–5 by the thruster limit and 6–7 by the action limit.
   Independently clip each regulator component to ±regulator_limit/100, then add.
3. Multiply by the configured row-major 8×8 allocation matrix.
4. With stabilization enabled, apply nullspace vectors sequentially. Each sees
   the prior vectors' modified thrust. Deadzone is ±0.003; activation is bounded
   to ±0.08. Divide/negate deadzones by nonzero vector entries, sort endpoints,
   then clip and merge forbidden intervals, including touching intervals.
5. Choose the available interval with fewest symmetric-difference crossings
   against remembered active-entry deadzone indices; then minimum distance to
   prior activation; then the **first** interval in sorted order. Jump to its
   nearest boundary or decay toward zero by 0.001 and clamp inside. No interval
   means zero activation and cleared history. Zero vectors are skipped.
   Same vector count preserves history even when values change; count changes
   reset all histories. Disable/re-enable does not itself reset NV history.
6. Reorder as `allocated[identifiers[i]]`, then multiply hardware-slot spin[i],
   then clip individually to ±1. Baseline permits duplicated identifiers.
7. Internal motor commands are float32 `1000 + 1000 * thrust`, truncated to
   integer 0–2000. Preserve the MCU's downstream physical PWM/DShot conversion
   separately; these are not physical 1500 µs-centered PWM values.

Calibration sends hardware channel +0.1, internal command 1100, with all others
1000, for 10 seconds. It bypasses smoothing, PID, allocation, nullspace,
permutation, spin and power limits. Countdown begins after its first successful
USB command write. Readiness loss ends in an error; cancellation sends neutral.
A backwards clock jump now rejects negative-age pilot input and ends a
negative-elapsed calibration with neutral/error. Valid-input timing is unchanged.
Custom Python action imports remain intact. Auto-tuning is out of scope.

## Configuration and command API

Custom actions use the state-owned awaited client:

```python
await state.set_desired_attitude((x, y, z, w))
await state.set_desired_depth(depth_meters)
```

The absolute setter normalizes finite nonzero XYZW and waits for application.
It does not enable stabilization or reset integral. A later enable edge retains
legacy leveling semantics. Mutating displayed Euler fields does not change the
Pico target. A failed desired-depth apply leaves local targets unchanged and
emits an existing translated warning, rather than failing only in logs.

Every Pico-owned mutation/import uses a complete 628-byte image, including output
protocol/rate, and one committed generation/digest. The Pi waits up to 8 seconds
for actual APPLIED, persists the candidate, then publishes canonical Config with
mutationId. Connected apps send ConfirmConfig before a success toast. Ordinary
confirmation tasks are separate from the connection-change blocker, so buffered
ConfirmConfig followed immediately by the next mutation is accepted.

The device can take up to 7 seconds to apply. Pi permits 14 half-second COMMIT
ACK attempts before querying the exact committed generation/digest within the
8-second overall budget. Old generation metadata is not proof of success.
App mutation timeout remains 12 seconds. No pending settings loading toast is
introduced.

Failure returns canonical persisted config plus optional `payload.error`, with
no success or ConfirmConfig on rejection. Malformed schema messages preserve
mutation correlation where the ID is recoverable. Outcome-unknown commits and
persistence failures inhibit output. Staged/queued/USB-written never means applied.

The wire has an explicit eight-vector nullspace bound. Oversized imports/startup
configs are rejected, not silently truncated. An unencodable current config
must not prevent a valid corrective candidate from being applied and persisted;
that repair path has a regression test. The representation limit remains a
compatibility consideration before release, not permission to remove UI knobs.

## Safety and maintenance

Fresh valid operator commands renew the 200 ms lease. USB activity, pressure and
new 500 Hz calculated output do not keep stale operator input valid. Pressure
expiry at 500 ms and IMU/core-1-output age have independent Pico gates. Pi also
invalidates IMU/control readiness when attitude/raw-IMU telemetry expires.
Recovery and firmware-operation output lockouts remain authoritative.

Capability negotiation sends fixed-size legacy C5 command 3 before extended
payloads. Frames validate length, version, session, sequence and CRC32C. Reliable
mutations pause streaming and retry the same request. Settings APPLIED verifies
the complete image generation and digest.

Before ESC upload, framed RAW neutral followed by reliable ENTER_MAINTENANCE
0x25 latches output off and closes the control session. Pi keeps its local latch
across upload, cancellation, abort and finally cleanup, preventing automatic
HELLO or streaming during that interval. Existing E7/E8 upload remains unchanged
inside maintenance authority. Exit needs fresh HELLO, full settings APPLIED and
fresh CONTROL. Recovery remains latched on failure; nonneutral legacy commands
cannot escape maintenance or negotiated mode.

A hardware starvation latch cancels pending mutations with NOT_READY, clears the
active session and settings identity, and poisons the failed session ID. Pi now
invalidates its session on NOT_READY or a negative stream ACK, terminates pending
retries, and chooses a different random session for reconciliation. HELLO may be
BUSY until physical neutral is serviced; that is not success. Fresh settings and
fresh CONTROL are mandatory before restoring authority.

## Portable verification

Run the repository's normal development environment:

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
PICO_CONTROLLER_SOURCE=/path/to/mcu-firmware/src/control/controller.c \
  uv run pytest tests/test_pico_differential.py -v
```

The last command compiles the actual pure C source into a host shared library.
Without that path, pytest explicitly skips 22 C checks; three frozen-source hash
checks still run. No C-generated expected values are substituted.

Coverage includes six seeded 5-second multirate trajectories; normal/FPV;
all stabilization/depth combinations; same-dt 60/500 Hz near-180-degree, quaternion
sign and pitch-limit cases; independent limits; action axes; zero-coefficient
coupling; mapping/spin order; sequential NV/history/count changes; integral clips;
gyro-only fallback; and the rejected-gyro derivative distinction. Quaternion and
integral tolerance is `3e-5` radians/units. Motor/work comparisons permit one
integer LSB where float32 rounding crosses a truncation boundary.

### Opt-in full-stack hardware runner

`scripts/pico_stack_acceptance.py` complements the MCU repository's direct-wire
smoke test. It uses real RovState, SerialManager, McuSensor, PressureSensor and
PicoControl paths. Its only behavioral guards select an explicit USB device,
require an exact development identity before settings/commands, and disable both
automatic flashing hooks. It does not fabricate ACKs or pressure/IMU data.

The coordinator must stop the original service and disconnect ESCs first. The
runner never stops/starts services or uploads firmware. Use the staged source
and the Pi's real Python environment, for example:

```sh
MANAFISH_PICO_CONTROL_DEVELOPMENT=1 \
PYTHONPATH=/path/to/staged-firmware/src \
/path/to/pi-python/bin/python /path/to/staged-firmware/scripts/pico_stack_acceptance.py \
  --execute --service-stopped --escs-disconnected \
  --config /path/to/read-only-known-baseline-config.json \
  --staging-dir /path/to/new-acceptance-directory \
  --port /dev/serial/by-id/EXPECTED-PICO \
  --expected-build-identity 'pico-control-dev:EXACT-BUILD' \
  > acceptance.json
```

The staging directory must not already exist. Primary configuration is read-only;
config and recovery paths are redirected into the new staging directory. Existing
primary ESC recovery state causes refusal, not an override. The helper restores
the staged baseline to Pico and disk, checks that the primary file is unchanged,
attempts neutral and serial shutdown in finally, and exits nonzero if restoration
or cleanup cannot be verified. Inspect any failed restoration before resuming the
original service; no failure is reported as silently successful.

Scenarios measure real pressure publications, attitude frames, host CONTROL writes
and full device statistics windows separately. They exercise already-enabled
absolute target setting and subsequent source-dt integration; actual Config
APPLIED/persistence/ConfirmConfig/success ordering; host validation rejection;
app-input expiry; paused CONTROL with live USB RX; calibration cancellation; and
maintenance entry/exit with fresh session/settings/control. JSON reports actual
counts/readback and labels untested areas explicitly.

Default measurement is 12 seconds; total scenario deadline is 120 seconds, plus
at most 15 seconds for cleanup. The production pressure loop is intentionally
infinite, so the helper runs it as a process-owned daemon thread and exits only
after bounded cleanup and JSON flush, rather than hanging on thread shutdown.
It is an acceptance executable, not a library to embed in another process.

All comparisons use local monotonic durations/counts. The coordinator observed
Pi and workstation wall clocks months apart; do not compare their wall timestamps.
The JSON does not claim powered-motor behavior, ESC programming/reception,
network/Tauri rendering, unplug fault injection, forced hardware starvation or
p99 timing unavailable in the v1 statistics frame. A source-dt sum or host write
rate is not substituted for measured device control executions.

## Evidence and remaining hardware gates

Final portable checks ran on the workstation at `2026-09-15T05:22:52Z`, after
all scoped production fixes and helper changes. This supersedes earlier 339/342
counts. The timestamp records local verification, not hardware timing.

| Check | Result |
| --- | --- |
| `uv run ruff format --check .` | Passed; 84 files |
| `uv run ruff check .` | Passed |
| `uv run ty check` | Passed |
| `PICO_CONTROLLER_SOURCE=... uv run pytest -q` | **344 passed** in 8.21 seconds; includes all 25 oracle/integrity checks |
| `git diff --check` | Passed |
| Acceptance helper `--help` | Passed without hardware access |
| Acceptance helper without execution consent | JSON refusal, exit 1; no staging directory created and no port opened |

Commands ran through `direnv exec .` in the managed firmware worktree. The tested
MCU `controller.c` hash was checked before and after pytest and did not change.
Portable artifact identities:

| File | SHA256 |
| --- | --- |
| MCU `src/control/controller.c` | `81bc2409c2f4bf12303c8a41281fed8d781f1c10838047032da6731cfd62b34f` |
| MCU `src/control/controller.h` | `6ccee334d36a0ffd9712c5c1a785b2d439e63de6633f0ef4fc66fdec06645e0f` |
| `scripts/pico_stack_acceptance.py` | `23482161dc93e6eafd017bc3bd047042962743095eb560d5b2d897283da792e0` |

The coordinator reported app commit `6a16ff5` with all app gates passing
(184 frontend and 45 Rust tests). The coordinator also verified the installed
BMI270 source/scales listed above. Those checks were not rerun on hardware by the
Python agent. No hardware has been accessed by this agent.

Coordinator hardware state: verified MCU image `b817d1d` is installed; its
identity was read back twice. The initial neutral smoke passed capability,
settings/invalid-settings/QUERY/empty-ABORT and setter-ACK steps, then failed
IMU health with Bosch `-3` (`DEV_NOT_FOUND`) and zero controller updates. This
occurs before reset/blob upload; zero configuration diagnostics are unread
defaults. A subsequent actual ENTER_MAINTENANCE APPLIED acknowledgment left the
Pico latched neutral. The original Pi service remains stopped; no experimental
service override has been installed.

The checked Python code is staged at
`/home/pi/pico-spi-attitude-500hz/stage/firmware`, with copies of the original
configuration and custom actions. Its real-runtime `--help` succeeded; the
full-stack runner and production service have not been run. Remote verified
original backups remain at `/home/pi/pico-spi-attitude-500hz/backup`. The
[backup ledger](docs/pico-control-validation/BACKUP.md) contains hashes and exact
rollback commands; [hardware evidence](docs/pico-control-validation/HARDWARE.md)
records the failed smoke. Primary source/configuration was not overwritten.

Before completion, append sanitized commands/results, repository commits/status,
image checksums/build identity, exact install/rollback paths and:

- Real RP2040 sensor ID/init/register state, finite fresh raw data and changing
  attitude; 15 Hz pressure and 60 Hz actual/desired telemetry measurements.
- Completed AHRS/PID counts, execution durations, missed deadlines and output
  ages over 5-second windows; maximum NV workload and USB backpressure evidence.
- Setter order/deduplication, config rejection/ACK loss/outcome recovery,
  stale input/USB/IMU/pressure/core-1 output and reconnect behavior.
- Calibration start/cancel/timeout, sticky maintenance/abort/recovery, and
  eventual real ESC programming tests under separately safe conditions.
- A measured headroom estimate for 1 kHz, never a claim that 1 kHz was tested.

ESCs are disconnected on the authorized bench. Powered motor behavior, actual
per-ESC reception/telemetry and ESC programming remain release gates. Temporary
absolute evidence paths are not a portable final handoff.

## Transfer and resume on another PC

A private portable export is prepared as
`/home/pi/pico-spi-attitude-500hz/pico-spi-attitude-500hz-handoff.tar.gz`.
It contains this document and evidence summaries, incremental Git bundles for
all three task branches, the selected Pico image and Bosch license, and an
artifact checksum manifest. It excludes passwords, the private Pi source
backup and the original configuration contents.

```sh
scp pi@10.10.10.10:/home/pi/pico-spi-attitude-500hz/pico-spi-attitude-500hz-handoff.tar.gz .
tar -xzf pico-spi-attitude-500hz-handoff.tar.gz
cd pico-spi-attitude-500hz-handoff
sha256sum -c SHA256SUMS
```

Bundles require the ordinary repositories and the baseline commits listed
above. Verify each bundle in its corresponding repository, then fetch its task
branch without switching or resetting the primary checkout:

```sh
git -C /path/to/app bundle verify /path/to/export/app.bundle
git -C /path/to/app fetch /path/to/export/app.bundle \
  refs/heads/feat/pico-spi-attitude-500hz:refs/heads/feat/pico-spi-attitude-500hz
```

Repeat with `firmware.bundle` and `mcu-firmware.bundle` in their own repositories.
Create Paseo-managed worktrees from those existing branches and read each
repository's `AGENTS.md`. Do not push, publish or deploy merely because source
checks passed. First resolve the physical IMU identification blocker, repeat the
zero-output smoke, and follow the remaining hardware gates above. Keep the
original Pi service stopped until deliberately restoring the old pairing or
starting an isolated, verified new pairing.

### Final freeze record

Production and helper are frozen after the post-review gates above. The final
regressions cover invalid-current-config repair, failed depth-setter feedback,
safety-NACK session replacement, and negative-age pilot/calibration clock faults.
The implementation is committed on `feat/pico-spi-attitude-500hz`; coordinator
documentation commits retain the later hardware evidence. No push, PR, tag,
release or version bump was performed. Hardware execution was coordinator-only.

MCU gates passed on the corrected source: format, lint, Pico/Pico2 builds,
141 Unity tests, five original startup/reporting regressions, Bosch/USB
emulators, 28 real-runtime regressions (also ASan/UBSan), and six offline smoke
helper tests. These include permanent CONTROL/RAW/pressure/IMU expiration across
clock wrap, neutral-output ingress stalls, queued-command and COMMIT-ACK races.

Physical IMU identification is the current blocker. Complete sensor, timing,
backpressure, actual-pressure, full-stack and production-service acceptance only
after resolving it. Existing PWM remains **50 Hz**; neither a controller counter
nor missing-ESC DShot transmission counts prove 500 Hz accepted motor updates.
The bundled-image incompatibility remains a release gate.
