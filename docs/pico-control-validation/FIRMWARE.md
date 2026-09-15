# Pi firmware verification

After the Python implementation was frozen, both the coordinator and the
independent reviewer reproduced:

| Command | Result |
| --- | --- |
| `uv run ruff format --check .` | Passed, 84 files |
| `uv run ruff check .` | Passed |
| `uv run ty check` | Passed |
| `PICO_CONTROLLER_SOURCE=/path/to/mcu-firmware/src/control/controller.c uv run pytest -q` | 344 passed, none skipped |
| `git diff --check` | Passed |

Run these in the firmware Nix/direnv environment. Without the source variable,
the ordinary suite deliberately skips the 22 native C differential cases;
that is not equivalent to the result above.

The follow-up review closed the oversized-configuration repair and formatting
findings. A stored nine-vector configuration remains unchanged and inhibited,
but an in-app correction to eight vectors now follows actual COMMIT ACK,
persistence, canonical Config, ConfirmConfig and success notification. No
vectors are silently truncated. Clock rollback invalidates stale pilot input;
failed depth setters warn without changing the local target projection.

No Python correctness blockers remained in that review. The existing bundled
legacy MCU assets are still a **release gate**, not compatible production
artifacts. The explicit verified-development exception is for bench deployment.
See `HANDOFF.md` for pairing and release order.

Coordinator log SHA256:
`00f986695a5bbab4a63f8703c1582876f9988298ac63df08db1b99673af17168`.
Retained at
`~/.local/state/manafishrov/pico-spi-attitude-500hz/evidence/firmware-final-gates.log`.

The hardware runner's help/refusal paths were checked. Its real-device scenarios
and the production service still need separate hardware results; automated
unit tests are not hardware certification.
