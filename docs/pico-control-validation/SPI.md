# Actual SPI comparison and restoration

The user confirms the previously specified Pico/IMU wiring. Do not repeat the
wiring-confirmation request or treat a wiring fault as established.

## Subsequent power-cycle result

The user reported power cycling. The Pi had also rebooted: its original service
was active and its boot journal recorded automatic flashing of Pico1.0.3-rc.6.
The coordinator stopped the service, verified the retained backup/image hashes,
and reinstalled the exact b817d1d UF2 with picotool verification. The live
extended identity matched `pico-control-dev:b817d1d3da14` before testing.

A fresh 20-second zero-output smoke still failed: chip00, Bosch-3, zero samples,
zero AHRS/PID updates. Thus the reported power cycle did not resolve the fault.
The weak-pull comparison below was not repeated after this power cycle.

Final cleanup succeeded with fresh HELLO, zero-power/zero-allocation settings
COMMIT, unacknowledged RAW neutral, and actual ENTER_MAINTENANCE APPLIED.
The original service is stopped and the test controller is latched neutral.
The service has not been persistently disabled or masked: rebooting the Pi can
restart it and replace the development Pico again.

Next useful evidence: supply voltage and CS/clock/data signals at the sensor.
A wiring fault remains unconfirmed. Retained interface state is less compelling
after the reported power cycle, but actual sensor-side signals remain unmeasured.

Private evidence: `power-cycle-service.log`, `power-cycle-reinstall.log`, and
`power-cycle-neutral-smoke.log`. The last includes both verified identity checks,
the failed smoke and final neutral acknowledgment; SHA256:
`38571dfe5a59d09eb7ff8296efb997ba1a64b59e0e1b2c8b6220167cfdf9e8d2`.

## Observed result

The coordinator installed the isolated motor-disabled probe, captured all
66 records, and restored the exact controller image. No read returned ID `24`.
All transfers completed, all recorded motor pad levels were zero, and the
minimum recorded CS-high interval was 502 us.

| Method / condition | Third byte in three identification reads |
| --- | --- |
| Production bytewise algorithm, mode 0, requested 4 MHz | `00 00 00` |
| SDK routine, same settings | `00 00 00` |
| Both routines at requested 100 kHz and 1 MHz | All `00` |
| Both routines at requested 4 MHz, mode 3 | All `00` |
| Software-driven SPI, same pins, mode 0, nominal 50 kHz | `00 00 00` |
| SDK mode 0 / 4 MHz with weak MISO pull-up | `ff ff ff` |
| Same configuration switched back to weak pull-down | `00 00 00` |

Each returned *transaction* was entirely `00,00,00` or `ff,ff,ff`, not merely
a mismatched ID byte. GPIO12's raw pad status reversibly changed from zero to
`070e0000` and back; INFROMPAD is bit17. Divider readback gave 3906250, 992063
and 99681 baud for the requested hardware rates. These are divider values,
not measured waveforms. The software-driven rate is nominal only.

This supports an **undriven or weakly driven receive node during the reads**.
It does not establish why. Agreement across independent SPI methods weakens a
FIFO/API-specific defect, SPI1 input routing error, excessive clock rate or
mode mismatch as the common explanation. No Bosch blob, conversion or AHRS
code runs in this probe.

Remaining uncertainties include sensor-side interface state, power and signals
at the actual sensor. Four-wire assumptions were shared by the experiments;
three-wire mode (`IF_CONF` bit0) was not checked or changed. Reflashing the Pico
does not power-cycle the IMU. A genuine sensor power cycle was the next
check requested at this point; its later failed result is recorded above. Keep the Pi powered/service stopped;
remove Pico/IMU power, including any independent sensor supply, then reconnect.
After reconnection, the coordinator must recheck service state and image
identity before repeating the neutral smoke. No sensor reset/register-write
experiment was performed by the probe.

If unchanged after a genuine power cycle, the useful next evidence is board
supply voltage and CS/SCK/MOSI/SDO at the sensor, ideally with a logic analyser
or scope. Correct incoming `80 00 00` bursts with flat SDO differ from a valid
`24` at the sensor that never reaches the Pico. Current logs are not that
physical waveform evidence.

One secondary observation: the SDK-only 100 kHz path sometimes sampled SCK high
after releasing CS. The SDK routine can return before the final clock tail;
this cannot explain universal failure because the bytewise path waits for
busy-clear and the software-driven path explicitly lowers SCK.

## Exact experiment

- Probe source commit: MCU `1e765e7` (isolated `scripts/spi_probe/`; production
  source/build configuration unchanged).
- Source SHA256: `0816163e4d50b2c8be355ab3603b83e098105799dfbc586365a0fe1ce9bb596d`.
- UF2 SHA256: `ec1b90c9ee149ed945e508fef9c4fc486743d5808f2447c21eaca14e715f86f7`.
- ELF SHA256: `799f3bd22e023d8db882295eab1dd28daf5a6f573038e97eb938b7522ff0c523`.
- Identity: `manafish-bmi270-read-only-spi-probe`, `diagnostic-1`, RP2040 Pico.
- Pull comparisons enabled; one run triggered by USB DTR, no automatic rerun.
- Scoped strict build/format/tidy, offline tests with pulls on/off, ASan/UBSan,
  repository format/test/lint gates passed. Coordinator independently ran the
  actual-source host tests under ASan/UBSan. Core0/core1 reservations: 4/2 KiB.

Device selection was serial `E66430A64B818B35`, original service inactive and
ESCs disconnected. Both flash operations used the installed picotool:

```sh
picotool load -v -x /home/pi/pico-spi-attitude-500hz/stage/spi_probe.uf2 -f --ser E66430A64B818B35
# Capture the one-shot report with CDC DTR asserted.
picotool load -v -x /home/pi/pico-spi-attitude-500hz/stage/pico-b817d1d.uf2 -f --ser E66430A64B818B35
```

## Restoration and procedural corrections

Both loads verified successfully. The restored live controller identity was
`pico-control-dev:b817d1d3da14`; the selected controller UF2 remains SHA256
`21f22a2eeb34bba47699468aadd3d0d50d284711db1f7438f36ef2749f683339`.

The first cleanup omitted settings application after reboot and received
NOT_READY for maintenance. Two interim attempts incorrectly awaited RAW
acknowledgment; successful RAW frames are deliberately unacknowledged. These
were coordinator helper mistakes, not sensor findings. All requests remained
neutral; no nonneutral command was sent.

The corrected real-device sequence succeeded:

1. Verify exact live identity; fresh HELLO.
2. Apply the full zero-power/zero-allocation/no-nullspace settings image and
   verify COMMIT generation/digest APPLIED. Physical outputs need this setup
   after a cold controller boot.
3. Send RAW neutral without awaiting a RAW ACK.
4. Await actual `ENTER_MAINTENANCE` APPLIED.

**Final recorded state: controller restored and latched neutral; original Pi
service stopped.** Primary Pi source/configuration and backups remain untouched.
The diagnostic image is not left installed. No 500 Hz control acceptance is
claimed.

## Evidence

Private workstation evidence directory:
`~/.local/state/manafishrov/pico-spi-attitude-500hz/evidence/`.
Remote install/capture/restore logs: `/home/pi/pico-spi-attitude-500hz/evidence/`.

- `spi-probe-capture.log`: SHA256
  `b6e66ef56cb9ade10f37ffa515c701c9a296ea9f2b7b64ec4b4fe8b6ea3bd5ce`.
- `spi-probe-final-neutral.log`: SHA256
  `9ccc0823dedcd0c27542c42f3300e9d9c820d02e214b4c77282fba5ede364816`.
- `spi-probe-install.log`, `spi-probe-restore.log`: verified flash records.
- Earlier failed cleanup logs are retained, not silently replaced.
