# Agent Instructions

This document provides guidelines for AI agents working in this repository.

## Build

The primary way to build the firmware is using Nix:
```sh
nix build .#pi4-imx477
```
Replace `pi4-imx477` with the target platform. See `README.md` for options.

## Linting

This project uses `ruff` for linting. Run it from the root directory:
```sh
ruff check .
```

## Testing

Tests are located in `src/tests`. These are integration tests and must be run on the target Raspberry Pi hardware, not on a development machine.

To run a test, SSH into the Pi, navigate to the test file, and execute it with python.

Example (on the Pi):
```sh
python src/tests/imu.py
```

## Code Style

- **Formatting**: Follow PEP 8 guidelines. Use `ruff format`.
- **Imports**: Group imports in the standard order: standard library, third-party, local application.
- **Types**: Use type hints for all function signatures.
- **Naming**: Use `snake_case` for variables/functions, and `PascalCase` for classes.
- **Error Handling**: Use `try...except` blocks for potential exceptions.
