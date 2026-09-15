# Runnable migration oracle

The three `*_b62cbee.txt` files are byte-for-byte `git show` snapshots from
firmware commit `b62cbeeec7448104a02cc7b8d22c5558b2310414` (origin/main at task
start). They are test input, not a second implementation or production fallback.
Do not regenerate expected outputs from the C implementation.

`test_pico_differential.py` loads these original functions with their original
relative imports. It drives the original target/depth methods once per 60 Hz
command and the original AHRS/PID/allocation methods once per 500 Hz control
step. The only scheduling adaptations are the documented AHRS/PID dt clamp
and limiting nullspace decay to one original increment per command.

Run the cross-repository check with the MCU worktree supplied explicitly:

```sh
PICO_CONTROLLER_SOURCE=/path/to/mcu-firmware/src/control/controller.c \
  uv run pytest tests/test_pico_differential.py -v
```

Without that source path the differential C test is reported skipped, not
passed. Snapshot integrity checks always run. No hardware is accessed.
