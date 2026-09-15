# App verification

Coordinator rerun against app commit
`6a16ff5b3a824714b243e82cd778136f52bdacf5` on
`feat/pico-spi-attitude-500hz`. The worktree was clean afterward.

Run from the app's Nix/direnv development environment:

| Command | Result |
| --- | --- |
| `bun run fmt:check` | Passed |
| `bun run lint` | Passed |
| `bun run fmt:rs:check` | Passed |
| `bun run lint:rs` | Passed |
| `bun run test` | 184 passed across 29 files |
| `cargo test --manifest-path src-tauri/Cargo.toml` | 45 passed |
| `git diff --check` | Passed |

The change preserves the existing exposed settings. Rejected canonical Config
responses retain their optional error through Rust and TypeScript, update the
canonical display, and reject the mutation waiter without ConfirmConfig or a
success notification. Config mutation timeout is 12 seconds.

These are automated frontend/backend checks, not a physical desktop-to-ROV
acceptance test or proof of haptic behavior on a connected controller.

Full coordinator log SHA256:
`860d94f6ff11eb6e064c8c47e7be131510903f6a77fc67f9855ef0dca8e82bf6`.
A private retained copy is in the workstation's
`~/.local/state/manafishrov/pico-spi-attitude-500hz/evidence/app-final-gates.log`;
the commands and results above are the portable record.
