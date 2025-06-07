# Manafish Pico Firmware

The Pico in the Manafish ROV is responsible for sending signals to the thrusters. All required dependencies for working with it are included in the main firmware on the Pi, so you can use the Manafish Pi for developing it.

## Build

To build the pico firmware, you need to have the `pico-sdk` installed including its submodules with the `PICO_SDK_PATH` environment variable set to the path of the SDK. We also need `arm-none-eabi-gcc` a cross compiler that lets us build for the pico. We also need `Cmake`, the build system generator and `make` to build the firmware.

Create the build directory:

```sh
mkdir build
```

Navigate to the build directory:

```sh
cd build
```

Run `Cmake` to generate the build files using the `CmakeLists.txt` in the parent directory:

```sh
cmake ..
```

Lastly, run `make` to build the firmware:

```sh
make
```

After the build completes successfully, you will find the `pico.uf2` file inside the `build` directory. This is the file you will flash onto the Pico.

## View firmware serial output

The firmware uses USB CDC to send log messages (`printf` statements) back to the connected computer, which is invaluable for debugging. To view this output, you need a serial monitor program like `screen`.

First find the Pico's serial address:

```sh
ls /dev/ttyACM* # use ls /dev/tty.usbmodem* on macOS
```

Then, use `screen` to connect to the Pico's serial address:

```sh
screen /dev/ttyACM0 115200
```

The last argument is the baud rate, which you should leave at `115200` unless you have changed it in the firmware.

To exit `screen` press **Ctrl+A**, then press **K**. It will ask for confirmation; press **Y**.
