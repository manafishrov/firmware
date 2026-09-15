# Hardware acceptance ledger

Hardware operations are coordinator-owned. ESCs are disconnected. No powered
motor behavior, ESC reception, or ESC programming is certified by this record.
See `BACKUP.md` for verified rollback artifacts and the current service state.

## Selected image

- MCU commit: `b817d1d3da143bbb1d56ce4a86ff0a15e5ae1f3c`, clean source.
- Expected capability identity: `pico-control-dev:b817d1d3da14`.
- Original RP2040 Pico, serial `E66430A64B818B35`, not Pico 2.
- UF2 SHA256: `21f22a2eeb34bba47699468aadd3d0d50d284711db1f7438f36ef2749f683339`.
- ELF SHA256: `e19a27a1d99414503ddd736624ea0baf7f1ee4e2eaabf307176956bf659d2a29`.
- UF2 size: 226,304 bytes; ELF text/data/BSS: 113064 / 0 / 89484 bytes.
- Core0 stack: `[0x2003c000, 0x20040000)`; heap limit `0x2003c000`.
  Core1 uses an explicit 8192-byte main-RAM stack.

Before flashing, all MCU quality gates and both Pico/Pico2 builds passed.
Coordinator reran format/test/diff checks: 141 Unity tests, five unchanged
startup/reporting regressions, Bosch and USB emulators, 28 runtime regressions,
and six offline bench-helper checks. All 28 runtime regressions also passed
ASan/UBSan. Runtime source SHA256:
`8b7acdc6fa0f4fc07520e96913d8df451c0acc0cfcc5416c7221720941a33ab5`.

## Installation

The staged UF2 hash was checked on both workstation and Pi. The original
service was inactive and a full original-image backup had been verified.
The first load command was rejected before touching hardware because picotool
rejected a separated `--ser` selection argument. Grouping device-selection
arguments at the end succeeded as user `pi`:

```sh
/nix/store/57mdzhk6idgrfqm8n8dlc721jzn360y5-picotool-2.2.0-a4/bin/picotool \
  load -v -x /home/pi/pico-spi-attitude-500hz/stage/pico-b817d1d.uf2 \
  -f --ser E66430A64B818B35
```

Exit status was zero, flash verification reported `OK`, and the application
restarted with `/dev/ttyACM0` present. Remote evidence:
`/home/pi/pico-spi-attitude-500hz/evidence/flash-b817d1d-r2.log` and `.exit`.

## Acceptance status

The initial 20-second zero-allocation/zero-power/no-nullspace smoke **failed**
with exit status 1: `IMU is not healthy; inspect MCU logs and wiring`.
Its pressure values were synthetic, not a physical pressure-sensor test.

Confirmed before that failure:

- Live capability identity matched `pico-control-dev:b817d1d3da14`; API 1,
  maximum payload 768 bytes, settings 628 bytes, maximum 8 vectors, features 0x1f.
- HELLO, actual settings COMMIT generation/digest acknowledgment, invalid-NaN
  settings rejection, QUERY of the retained configuration, empty ABORT and
  quaternion/depth setter acknowledgments completed without assertion failure.
- No nonneutral reported motor command was observed in the zero-output test.
- The hardware explicitly reported zero AHRS/PID/depth updates. **500 Hz control
  has not been demonstrated.**

Representative diagnostic:

```text
BMI270 chip=00 init=0 internal=00 err=00 status=00 cfg=00/00/00/00 pwr=00/00 time=000000 samples=0 result=5 bosch=-3 bus_timeouts=0
```

Bosch `-3` is `BMI2_E_DEV_NOT_FOUND`: identification failed before reset,
configuration-image upload or settings readback. The ID mismatch is retained
by the Bosch driver. The other zero diagnostic fields are unread initialized
values, not evidence that those physical registers returned zero or that the
configuration blob failed.

One five-second window reported AHRS/PID/depth all 0 Hz, 20 missed slots,
31 us average and 11241 us maximum with five sensor errors. Repeated sensor-init
attempts include startup delays. The roughly 1.6% duty is **not** functioning
controller headroom. DShot counters reported approximately 427–428 transmitted
frames/s per motor under missing-ESC receive timeouts; this is neither ESC
acceptance nor a loaded 500 Hz actuation result.

Full failed-smoke log SHA256:
`a0ad6a407dc30337cd31796fb26a5c542a274e055ff505c94aa607731ae21e51`.
Remote: `evidence/smoke-neutral-b817d1d.log` under the experiment directory;
a private copy is retained in the workstation evidence directory.

## Safe state after failure

The coordinator subsequently re-probed the exact live identity, started a
fresh HELLO, sent framed RAW neutral, and received APPLIED for
`ENTER_MAINTENANCE` (0x25). The Pico is **latched in neutral maintenance**;
no Pi service or control stream is running. The next valid session must still
perform HELLO, full settings application and fresh CONTROL.

## Initial checks, superseded by completed SPI comparison

The user subsequently confirmed the wiring. [SPI.md](SPI.md) records the actual
bytewise/SDK/software-SPI comparison, reversible weak-pull result, and successful
controller restoration. Use that record for next steps; do not repeat the
wiring-confirmation request. The following board information is retained as
reference, not a finding that the connections are wrong. For the documented full-size SparkFun BMI270 primary SPI interface:

| Pico | SparkFun primary interface |
| --- | --- |
| GP10 | SCL / SCK |
| GP11 | SDA / PICO / MOSI |
| GP12 | ADR / POCI / MISO — **not OSDO** |
| GP13 | CS |
| 3V3, GND | Matching supply and common ground |

Official board documentation requires the address jumper fully open for SPI.
Its schematic uses a 100 kΩ bias, not a direct ground short: a closed jumper alone
has **not** been proved to cause this failure. The Micro board has different
accessibility; obtain the exact model/photo. Disconnect power before physical
changes. No wiring fault is claimed as confirmed yet.

Read-only source checks found no motor-pin collision (motors use GP6–9 and
GP18–21), and the mode 0/dummy-read path matches upstream drivers. Bosch's
450 us delay after the discarded first ID read satisfies its documented 200 us
SPI-selection interval. Expected startup transactions each send `80 00 00`
under one CS assertion; the second transaction's third received byte should be
`24`. A correct response at the sensor but zero in firmware implicates the RX
path; flat sensor output with correct incoming signals still leaves board,
power and interface selection unresolved.

Sources:
[SparkFun pinned hardware overview](https://github.com/sparkfun/SparkFun_Qwiic_6DoF_BMI270/blob/c8bb01b27e91e4985eb9d526cc59eb7421a08bbb/docs/hardware_overview.md#L80-L101)
and [Bosch BMI270 datasheet, §6](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf). Ranked
remaining hypotheses are wrong/unconnected primary MISO or power/CS wiring,
board/interface selection, then signal integrity or bus-speed sensitivity.
Do not substitute synthetic input for missing real-sensor acceptance.

After resolving the sensor response (see the latest checks in SPI.md), rerun
the neutral smoke first. Only after IMU
identification/freshness succeeds should stress, USB-backpressure, full Python
stack and production-service acceptance proceed. Existing PWM remains 50 Hz;
500 Hz computation is not 500 Hz PWM or proof of reception by disconnected ESCs.
