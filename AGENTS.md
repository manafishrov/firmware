# AGENTS.md

## Purpose

Firmware that runs on the Manafish Pi (Raspberry Pi 3B + IMX477). Python
service shipped as a NixOS SD image via `nixos-raspberrypi`. Talks to the
ROV's MCU (`mcu-firmware`) and to the desktop `app` over WebSocket.

## Stack

- Python 3.13 (uv-managed), `numpy`, `scipy`, `pydantic`, `websockets`
- NixOS image build (`nix build .#pi3-imx477`)
- Ruff (lint + format), `ty` for type-checking, `pytest`
- pre-commit + uv

## Structure

- `src/rov_firmware/` — service entrypoint and modules
- `src/tools/` — operator CLI (`uv run tools …`)
- `tests/` — pytest suite
- `nix/` — NixOS modules (`firmware.nix`, `camera.nix`, `sensors.nix`,
  `networking.nix`, `mcu.nix`, `system.nix`, `impermanence.nix`)
- `pyproject.toml`, `uv.lock` — Python deps and pins
- `flake.nix`, `flake.lock` — image inputs
- `scripts/`, `keys/` — build helpers and image keys

## Commands

Use the dev shell (`nix develop` or direnv). Then:

- Sync deps: `uv sync`
- Run service locally: `uv run start`
- Operator CLI: `uv run tools …`
- Sync python deps from nix: `./sync-python-deps.sh`

### Quality (must pass before flashing or merging)

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Auto-fix: `uv run ruff format .` and `uv run ruff check --fix .`.

### Image build & flash

```sh
nix build .#pi3-imx477
ls -lh result/sd-image
# Flash per README.md (zstd | dd, or Rufus on Windows)
```

Pre-commit hook runs Ruff on staged files. Install once: `uv run pre-commit
install`.

## Rules

- The runtime Python environment is the one in `nix/firmware.nix` (built from
  `nixpkgs` + flake inputs). `pyproject.toml` exists for tooling (uv, pytest,
  type checker) and **must stay in sync** with what nixpkgs/flake actually
  provides — otherwise local dev sees different versions than the image.
- Don't hand-edit Python pins in `pyproject.toml`. Run `./sync-python-deps.sh`
  (uses `nix eval` against the locked nixpkgs and `flake.lock` for git inputs)
  after any nix bump. The `sync-python-deps` CI workflow runs this on every
  PR that touches `flake.lock`/`nix/**` and pushes the diff back, so Renovate
  PRs stay self-correcting. Renovate itself can't do this — it doesn't
  resolve `nixpkgs#python313Packages.<pkg>.version`.
- Custom Python packages (`numpydantic`, `bmi270`, `ms5837`) live as flake
  inputs and as `buildPythonPackage` definitions in `nix/firmware.nix`. Keep
  both in sync — Renovate updates the nix copy via custom managers; the sync
  script then propagates them to `pyproject.toml`.
- Python version is pinned in `pyproject.toml` and `nix/firmware.nix`. The
  sync script handles this too — bump it in `nix/firmware.nix`.
- Don't write plaintext secrets. Image keys in `keys/` are gitignored.
- Match existing module style; keep modules small and typed.
- Don't add dependencies without reason.
- Don't push without being asked. CI builds the image on tags.

## Releases

**Never cut a release without being explicitly asked, and confirm the version
and release notes back to the user before doing anything.**

- Releases for `firmware` are independent of `app`. Do not match versions.
- Bump version in:
  - `pyproject.toml` → `[project] version`
  - `uv.lock` is updated by running `uv lock` (or `uv sync`)
- Commit message: `chore(release): vX.Y.Z`.
- Tag: `git tag vX.Y.Z` then `git push --tags` — pushing the tag triggers
  `.github/workflows/build.yaml` which builds the SD image, signs it
  (minisign), uploads to S3, and creates a **draft** GitHub release. Edit
  and publish manually.
- Pre-releases use `vX.Y.Z-rc.N` and are auto-marked prerelease.
- Quality gates above must pass first.

Workflow before tagging: confirm the bumped version with the user, confirm
the release notes text, then commit, tag, push.

## Commits

Conventional Commits, focused on **why**.

```
<type>(<scope>): <subject>

[body explaining why, ~72 char wrap]
```

- Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `chore`, `ci`, `build`,
  `revert`. `chore(deps)` reserved for Renovate.
- Scopes: `firmware`, `tools`, `nix`, `camera`, `sensors`, `mcu`,
  `networking`, `system`, `flake`, `ci`.
- Subject: imperative, lowercase, ≤72 chars, no period.

## Keep this file useful

If you change Python/Nix entry points, rename a module under `nix/`, swap a
linter, or alter the quality gates — update this file (and any matching
Renovate `customManagers` paths) in the same commit.
