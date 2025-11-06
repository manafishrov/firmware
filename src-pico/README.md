# Manafish Pico Firmware

The Pico in the Manafish ROV is responsible for sending signals to the thrusters. All required dependencies for working with it are included in the main firmware on the Pi, so you can use the Manafish Pi for developing it.

## Prerequisites

- `pico-sdk`
- `clang-format` and `clang-tidy` for code formatting/linting
- `picotool` for flashing
- `arm-none-eabi-gcc`, CMake, Make

## Available Commands

Run `make help` for a full list. Key targets:

- `make build` - Build both DShot and PWM firmware
- `make build-dshot` / `make build-pwm` - Build specific firmware
- `make flash-dshot` / `make flash-pwm` - Build and flash
- `make copy` - Build and copy to main firmware
- `make clean` - Clean build directory
- `make format` - Format code
- `make lint` - Lint code

## Build

To build the Pico firmware, ensure the `pico-sdk` is available. The Makefile handles CMake configuration and building.

Navigate to the src-pico directory:

```sh
cd src-pico
```

To build DShot firmware:

```sh
make build-dshot
```

To build PWM firmware:

```sh
make build-pwm
```

To build both:

```sh
make build
```

The `.uf2` files will be in `build/dshot/dshot_firmware.uf2` and `build/pwm/pwm_firmware.uf2`. For rebuilds, the Makefile reconfigures only when needed.

## Flash

Ensure `picotool` is installed. The Makefile handles flashing after building.

To flash DShot firmware:

```sh
make flash-dshot
```

To flash PWM firmware:

```sh
make flash-pwm
```

This works regardless of BOOTSEL mode.

## Add to Firmware

To copy the Pico firmware into the main Manafish firmware:

```sh
make copy
```

This builds both and copies `dshot_firmware.uf2` to `src/microcontroller_firmware/dshot.uf2` and `pwm_firmware.uf2` to `src/microcontroller_firmware/`.

## View firmware serial output

The firmware uses USB CDC to send log messages (`printf` statements) back to the connected computer, which is invaluable for debugging. To view this output, you need a serial monitor program like `screen`.

First find the Pico's serial address:

```sh
ls /dev/ttyACM* # use ls /dev/tty.usbmodem* on darwin
```

Then, use `screen` to connect to the Pico's serial address:

```sh
screen /dev/ttyACM0 115200
```

The last argument is the baud rate, which you should leave at `115200` unless you have changed it in the firmware.

To exit `screen` press **Ctrl+A**, then press **K**. It will ask for confirmation; press **Y**.
