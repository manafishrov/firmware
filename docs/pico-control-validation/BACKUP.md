# Hardware backup and deployment ledger

Task: `pico-spi-attitude-500hz`. Hardware access is coordinator-owned.
No passwords or private backup contents belong in this repository.

## Current state — migration image installed, IMU identification blocked

- Pi reachable at `pi@10.10.10.10`; original RP2040 Pico serial
  `E66430A64B818B35`, USB CDC `/dev/ttyACM0`.
- `manafish-firmware.service` is **stopped** to prevent competing USB access
  and automatic firmware reconciliation.
- Original `/home/pi/firmware` is unchanged. No service override is installed.
- Migration image from MCU commit `b817d1d3da143bbb1d56ce4a86ff0a15e5ae1f3c`
  is now installed: verified `picotool load` and application restart succeeded.
  Image SHA256 is
  `21f22a2eeb34bba47699468aadd3d0d50d284711db1f7438f36ef2749f683339`.
- The zero-output smoke failed at IMU identification; see `HARDWARE.md`.
  The Pico was subsequently left in acknowledged sticky neutral maintenance.
  Before replacement, a checksum-valid D6 reply confirmed original `1.0.3-rc.6`.
- ESCs are disconnected. Motor behavior and actual ESC programming cannot be
  certified on this bench.

The Pi clock reports March 2026 while the workstation reports September 2026.
Use monotonic clocks and device counters for measurements, not cross-machine
wall-clock differences. Connectivity and the backup hash were rechecked after
session continuation; the original service remained inactive.

## Verified backups

Private remote directory: `/home/pi/pico-spi-attitude-500hz/backup/`.
Directory permissions are 0700; backup files are 0600, owned by `pi:users`.

| File | SHA256 |
| --- | --- |
| `pico-original-full.uf2` | `df9fb60833434bde2424ef6185638775d0ebb9e47a3d631e18238c9bbe3d0160` |
| `pi-firmware.tar.gz` | `87876cbfdc9fa17ab431ec9fa5a7c12b6fa7a5c6785def75ae2584868840bf64` |
| `config.json` | `3fa6365600860975e0aaadb20feb8475c1827e934906e9f63131452ce5fbfb70` |

`SHA256SUMS` and `service-before.txt` are alongside them. The source archive
contains the original installed Pi tree; keep it private rather than adding it
to a public repository or release.

The original UF2 is 4,194,304 bytes (a full 2 MiB flash dump in UF2 format).
`picotool save -a -v` completed and verified the flash contents. A downloaded
copy initially matched the remote hash. Local temporary evidence was lost on
session continuation; the remote backup was subsequently rechecked and remains
intact. A replacement private copy was downloaded and hash-verified at
`~/.local/state/manafishrov/pico-spi-attitude-500hz/backup/pico-original-full.uf2`.
Keep a verified private copy when moving to another PC.

Image metadata identifies RP2040, board `pico`, SDK 2.1.1, Release build,
flash range `0x10000000..0x1000fcb8`. The D6 reply, not the filename or build
metadata, establishes the original release version.

## Isolated source staging

The checked Python source and acceptance runner were unpacked into
`/home/pi/pico-spi-attitude-500hz/stage/firmware/`. The original configuration
and installed custom-action files were copied there, without changing the
original tree. Staged and original configuration hashes matched the backup.
The runner's `--help` path succeeded using the Pi's installed Python environment;
the full-stack runner has not been executed. The separate MCU smoke failed
as recorded in `HARDWARE.md`.

Source archive SHA256:
`ea0e9f7a74adda2dfe3e0de453ff2dcdf002339eb246ec1fd7fa059d02603515`.
The archive includes documentation from before this staging entry; later
source changes must be staged and recorded explicitly.

## Tools and rollback

Installed Python:

```text
/nix/store/3yi65bxmxm3p95adl14cahcrxyyxj7w3-python3-3.13.14-env/bin/python3
```

Installed picotool:

```text
/nix/store/57mdzhk6idgrfqm8n8dlc721jzn360y5-picotool-2.2.0-a4/bin/picotool
```

The migration image is installed. To roll back, stop any experimental process
and restore both sides, not just the Pi service:

```sh
sudo systemctl stop manafish-firmware.service
sudo /nix/store/57mdzhk6idgrfqm8n8dlc721jzn360y5-picotool-2.2.0-a4/bin/picotool \
  load -v -x /home/pi/pico-spi-attitude-500hz/backup/pico-original-full.uf2 \
  -f --ser E66430A64B818B35
sudo systemctl start manafish-firmware.service
```

If subsequent deployment adds a service override or separate experimental
service, record its exact reversal here before starting it. Do not unpack the
source backup over the original tree unless restoration is actually needed.
The original Pi software expects its previous IMU wiring; restoring software
alone does not undo the physical SPI migration.

## Before continuing

1. Retain corrected MCU commit `b817d1d` and its passing safety regressions;
   the earlier `7f152f8` alone is unsafe.
2. All corrected-source quality gates passed. Rerun them after any code change.
3. Keep and verify the private original UF2 copy before further flashing.
4. Resolve physical IMU identification, rerun the neutral smoke, and record the
   exact tested commit, image hash, commands and results.
5. Use a separate Pi source directory. The development reconciliation exception
   requires both `MANAFISH_PICO_CONTROL_DEVELOPMENT=1` and a verified compatible
   `pico-control-dev:` identity. Existing bundled legacy images are not compatible.
