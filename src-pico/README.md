# Manafish Pico Firmware

The Pico in the Manafish ROV is responsible for sending signals to the thrusters. All required dependencies for working with it are included in the main firmware on the Pi, so you can use the Manafish Pi for developing it.

## Build

To build the pico firmware, you need to have the `pico-sdk` installed including its submodules with the `PICO_SDK_PATH` environment variable set to the path of the SDK. We also need `arm-none-eabi-gcc` a cross compiler that lets us build for the pico. We also need `Cmake`, the build system generator and `make` to build the firmware.

You can build either the dshot or pwm firmware by specifying the FIRMWARE_TYPE option when running cmake:

Create the build directory:

```sh
mkdir src-pico/build
```

Navigate to the build directory:

```sh
cd src-pico/build
```

To build dshot firmware:

```sh
cmake -DFIRMWARE_TYPE=dshot ..
```

To build pwm firmware:

```sh
cmake -DFIRMWARE_TYPE=pwm ..
```

Lastly, run `make` to build the firmware:

```sh
make
```

After the build completes successfully, you will find the `.uf2` file inside the `build` directory. This is the file you will flash onto the Pico. For subsequent builds, you can skip the `cmake` step and just run `make` to rebuild the firmware in the `build` directory.

## Flash

We need to have `picotool` installed to flash the firmware onto the Pico.

After building, the .uf2 file will be located in either `build/dshot/` or `build/pwm/`, depending on which firmware you built.

To flash the DShot firmware:

```sh
picotool load -f -x dshot/dshot_firmware.uf2
```

To flash the PWM firmware:

```sh
picotool load -f -x pwm/pwm_firmware.uf2
```

This should work regardless of if the Pico is in BOOTSEL mode or not.

## Add to firmware

To make the pico firmware part of the main Manafish firmware, you need to copy the built `.uf2` file to the `src` directory. You can do this with the following commands:

```sh
cp src-pico/build/dshot/dshot_firmware.uf2 src/microcontroller_firmware/dshot.uf2
cp src-pico/build/pwm/pwm_firmware.uf2 src/microcontroller_firmware/pwm.uf2
```

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
